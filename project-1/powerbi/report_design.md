# Power BI Report: Workforce Forecast Simulator

## Prerequisites

- Power BI Desktop installed
- PostgreSQL `wfm` database loaded (schema + data + views from steps 1-5)
- CSV files in `data/results/`: `kpi_summary_60m.csv`, `model_quality_60m.csv`

---

## Step 1: Connect to Data

### PostgreSQL connection

1. Open **Power BI Desktop**
2. **Home > Get Data > Database > PostgreSQL database**
3. Server: `localhost`, Database: `wfm` > **OK**
4. Enter credentials (user: `postgres`, your password), select **Database** tab
5. In the Navigator, expand schema `wfm` and check:
   - `vw_contacts` (60,480 rows — contact volume + service metrics joined with time attributes)
   - `vw_staffing` (60,480 rows — agent scheduling + costs joined with time attributes)
   - `dim_channel` (3 rows — voice, chat, email)
   - `dim_queue` (7 rows — billing, tech, sales, web_support, sales_chat, support_email, billing_email)
   - `dim_time` (8,640 rows — every 15-min interval across 90 days)
6. Click **Load**

### CSV data sources

1. **Home > Get Data > Text/CSV** > navigate to `data/results/kpi_summary_60m.csv` > **Load**
   - 588 rows: daily KPIs per scenario per channel (7 scenarios x 4 weeks x 3 channels x ~7 days)
   - Rename to `scenario_kpis` in the Fields pane (right-click > Rename)
2. Repeat for `data/results/model_quality_60m.csv` > **Load**
   - 7 rows: MAPE and RMSE per channel/queue
   - Rename to `model_quality`

### Validation

After loading, check row counts in the bottom-right of each table preview:
- `vw_contacts`: ~60,480 rows
- `vw_staffing`: ~60,480 rows
- `scenario_kpis`: ~588 rows
- `model_quality`: 7 rows

---

## Step 2: Data Model and Relationships

### Why a star schema

The `wfm` database uses a star schema: fact tables (`vw_contacts`, `vw_staffing`) at the center, dimension tables (`dim_channel`, `dim_queue`, `dim_time`) around them. This lets you slice any metric by any dimension — for example, "show me service level for voice/billing on Mondays at 10am."

### Switch to Model view

Click the **Model** icon (3rd icon, left sidebar). You'll see all tables laid out. Power BI may auto-detect some relationships.

### Create these relationships

For each: click **Home > Manage relationships > New**, then set the fields, cardinality, and cross-filter direction.

| From (Many) | To (One) | Cardinality | Cross-filter | Why |
|---|---|---|---|---|
| `vw_contacts[channel_name]` | `dim_channel[channel_name]` | Many-to-One | Single (dim→fact) | Filter contacts by channel type (voice/chat/email) and real-time flag |
| `vw_staffing[channel_name]` | `dim_channel[channel_name]` | Many-to-One | Single (dim→fact) | Filter staffing by channel type |
| `vw_contacts[queue_name]` | `dim_queue[queue_name]` | Many-to-One | Single (dim→fact) | Filter contacts by skill queue (billing, tech, sales, etc.) |
| `vw_staffing[queue_name]` | `dim_queue[queue_name]` | Many-to-One | Single (dim→fact) | Filter staffing by skill queue |
| `vw_contacts[ts_start]` | `dim_time[ts_start]` | Many-to-One | Single (dim→fact) | Enable time-based filtering (date, dow, hour) across contact metrics |
| `vw_staffing[ts_start]` | `dim_time[ts_start]` | Many-to-One | Single (dim→fact) | Enable time-based filtering across staffing metrics |

**Why Single cross-filter direction?** With two fact tables (contacts and staffing) sharing the same dimensions, bidirectional filtering would create ambiguous paths. Single direction means filters flow from dimensions to facts only, which is the correct behavior for a star schema.

**Note:** The `scenario_kpis` and `model_quality` CSV tables are standalone — they don't need relationships because they contain pre-aggregated data that won't be cross-filtered with the main fact tables.

### Verify

After creating relationships, you should see lines connecting each fact table to the three dimension tables, with `1` on the dimension side and `*` on the fact side.

---

## Step 3: DAX Measures

Switch to **Report** view (1st icon, left sidebar). For each measure: right-click the target table in the Fields pane > **New measure**, paste the formula, press Enter.

### Volume Measures (on `vw_contacts`)

These measure the raw demand hitting your contact center.

**Offered Contacts** — Total inbound contacts across all intervals in the current filter context:
```DAX
Offered Contacts = SUM('vw_contacts'[offered_contacts])
```

**Handled Contacts** — Contacts actually answered by agents (offered minus abandoned):
```DAX
Handled Contacts = SUM('vw_contacts'[handled_contacts])
```

**Abandoned Contacts** — Contacts that hung up or disconnected before reaching an agent:
```DAX
Abandoned Contacts = SUM('vw_contacts'[abandoned_contacts])
```

**Abandon Rate** — What fraction of offered contacts were abandoned. In WFM, anything above 5% is concerning; above 10% signals serious understaffing:
```DAX
Abandon Rate = DIVIDE([Abandoned Contacts], [Offered Contacts], 0)
```
*Format: Percentage, 2 decimal places*

The `DIVIDE` function is used instead of `/` because it handles division by zero gracefully (returns 0 instead of an error). This matters for intervals where no contacts were offered (e.g., overnight email).

### Service Measures (on `vw_contacts`)

These measure how well the contact center meets its SLA commitments.

**Avg Service Level** — The mean proportion of contacts answered within the SLA threshold. The threshold differs by channel (voice: 20s, chat: 30s, email: 24h). A value of 0.80 means 80% of contacts were answered in time:
```DAX
Avg Service Level = AVERAGE('vw_contacts'[service_level])
```
*Format: Percentage, 1 decimal place*

**Avg ASA** — Average Speed of Answer in seconds. This is how long a customer waits before reaching an agent. Computed by the Erlang C model for real-time channels (voice/chat). Lower is better — industry target is typically under 30 seconds for voice:
```DAX
Avg ASA Seconds = AVERAGE('vw_contacts'[asa_seconds])
```
*Format: Decimal number, 1 decimal place*

**SLA Attainment** — What percentage of 15-minute intervals met the SLA target. Unlike Avg Service Level (which averages the SLA percentage), this is a binary pass/fail per interval. It answers: "How often are we meeting our commitment?"

Each channel has a different SLA target:
- Voice: 80% of calls answered in 20 seconds
- Chat: 75% of chats answered in 30 seconds
- Email: 90% resolved in 24 hours

```DAX
SLA Attainment =
AVERAGEX(
    'vw_contacts',
    IF(
        'vw_contacts'[service_level] >=
            SWITCH(
                'vw_contacts'[channel_name],
                "voice", 0.80,
                "chat", 0.75,
                0.90
            ),
        1,
        0
    )
)
```
*Format: Percentage, 1 decimal place*

The `SWITCH` function maps each channel to its SLA target. `AVERAGEX` iterates every row, marks it 1 (met) or 0 (missed), then averages — giving the proportion of intervals that met SLA.

### Staffing and Cost Measures (on `vw_staffing`)

**Scheduled Agents** — Total agents on the schedule (before shrinkage):
```DAX
Scheduled Agents = SUM('vw_staffing'[agents_scheduled])
```

**Available Agents** — Agents actually available to take contacts (after shrinkage — breaks, meetings, training, absenteeism). This is always less than scheduled:
```DAX
Available Agents = SUM('vw_staffing'[agents_available])
```

**Avg Shrinkage Rate** — What percentage of scheduled agents are unavailable. Typical call centers run 25-35% shrinkage. Higher shrinkage means more overstaffing is needed to meet SLA:
```DAX
Avg Shrinkage Rate = AVERAGE('vw_staffing'[shrinkage_rate])
```
*Format: Percentage, 1 decimal place*

**Labor Cost** — The total labor cost for scheduled agents across all intervals. Calculated as: agents_scheduled x cost_per_hour x (interval_minutes / 60). We divide by 60 because `cost_per_hour` is hourly but each row represents a 15-minute interval (0.25 hours):
```DAX
Labor Cost =
SUMX(
    'vw_staffing',
    'vw_staffing'[agents_scheduled]
        * 'vw_staffing'[cost_per_hour]
        * ('vw_staffing'[interval_minutes] / 60.0)
)
```
*Format: Currency ($), 0 decimal places*

`SUMX` is required here (instead of `SUM`) because we need to multiply three columns row-by-row before summing. `SUM` can only aggregate a single column.

**Staffing Gap** — The difference between scheduled and available agents. Positive = overstaffed (more agents than needed), negative = understaffed. This quantifies the impact of shrinkage:
```DAX
Staffing Gap = [Scheduled Agents] - [Available Agents]
```

### Forecast Accuracy Measures (on `model_quality`)

These come from the pre-computed model quality CSV. They measure how well the forecasting model predicts demand.

**MAPE** — Mean Absolute Percentage Error. The average percentage by which the forecast deviates from actual demand. Lower is better. Under 20% is good for call center forecasting; under 10% is excellent:

No DAX needed — the `mape` column in `model_quality` is pre-computed. Just drag it into visuals directly.

**RMSE** — Root Mean Squared Error. Like MAPE but penalizes large errors more heavily (due to squaring). Useful for spotting models that are usually accurate but occasionally very wrong:

Same — use the `rmse` column directly.

---

## Step 4: Report Page 1 — Executive Summary

**Business purpose:** Give leadership a single-page view of contact center health: volume, cost, service quality, and trends over the 90-day period.

### KPI Cards (top row)

Create four **Card** visuals across the top:

1. Click empty canvas > **Visualizations > Card**
2. Drag `Offered Contacts` measure to the **Fields** well
3. In **Format** pane (paint roller): set font size to 24, display units to **Thousands** if values are large
4. Repeat for `Labor Cost`, `Avg Service Level`, `Abandon Rate`
5. Arrange in a row across the top of the page

### Volume Trend (left, below cards)

Shows daily contact volume over 90 days. Look for weekly patterns (dips on weekends) and the upward trend built into the data (+0.08%/day).

1. Click empty area > **Visualizations > Line chart**
2. **X-axis**: `dim_time[date_key]`
3. **Y-axis**: drag both `Offered Contacts` and `Handled Contacts` measures
4. The gap between the two lines represents abandoned contacts
5. **Format > Data colors**: set Offered to blue, Handled to green

### Channel Breakdown (right, below cards)

Shows how volume splits across voice, chat, and email. Voice should dominate (~41 contacts/15min base rate vs 18 for chat and 10 for email).

1. Click empty area > **Visualizations > Clustered bar chart**
2. **Y-axis**: `dim_channel[channel_name]`
3. **X-axis**: `Offered Contacts` measure

### Slicers

1. Add a **Slicer** > drag `dim_channel[channel_name]` > set to **List** style
2. Add a **Slicer** > drag `dim_time[date_key]` > set to **Between** (date range)
3. Position both in the top-right corner

### Rename the page tab

Double-click the page tab at the bottom > type `Executive Summary`

---

## Step 5: Report Page 2 — Forecast Quality

**Business purpose:** Evaluate how accurate the forecast model is. Poor forecast accuracy leads to either overstaffing (wasted labor cost) or understaffing (missed SLA). This page helps identify which channels/queues need forecast improvement.

Click **+** to add a new page, rename to `Forecast Quality`.

### MAPE by Channel/Queue (bar chart)

1. Click empty area > **Visualizations > Clustered bar chart**
2. Data source: `model_quality` table
3. **Y-axis**: `queue`
4. **X-axis**: `mape` (it will auto-aggregate as Sum — change to **Don't summarize** by clicking the dropdown arrow on the field)
5. **Legend**: `channel`
6. **Format > Data labels**: toggle **On** to show values on bars

### RMSE by Channel/Queue (bar chart)

1. Repeat the same layout with `rmse` on the X-axis
2. Place side-by-side with the MAPE chart

### Interpretation card

Add a **Text box** (**Insert > Text box**) explaining the metrics:
```
MAPE (Mean Absolute Percentage Error): Average % deviation of forecast from actual.
  < 10% = Excellent  |  10-20% = Good  |  20-50% = Fair  |  > 50% = Poor

RMSE (Root Mean Squared Error): Penalizes large forecast misses more heavily.
Lower is better. Compare across queues to find problem areas.

Holdout: 14 days of data were withheld from training to evaluate forecast quality.
```

---

## Step 6: Report Page 3 — Staffing Gap Heatmap

**Business purpose:** Identify when the contact center is overstaffed or understaffed by hour-of-day and day-of-week. This is the most actionable page for workforce planners — it shows exactly which shifts need more or fewer agents.

Add a new page, rename to `Staffing Heatmap`.

### Heatmap Matrix

1. Click empty area > **Visualizations > Matrix**
2. **Rows**: `vw_staffing[dow]` — this is 0-6 where 0=Monday, 6=Sunday
3. **Columns**: `vw_staffing[hour]` — this is 0-23
4. **Values**: `Staffing Gap` measure

Apply conditional formatting to color-code the cells:
5. In the **Format** pane > **Cell elements > Background color** > toggle **On**
6. Click **fx** (conditional formatting)
7. **Format style**: Gradient
8. **What field should we base this on?**: `Staffing Gap`
9. **Minimum**: color = red (this represents the most understaffed intervals)
10. **Center**: value = 0, color = white
11. **Maximum**: color = green (overstaffed)
12. Click **OK**

**Reading the heatmap:** Red cells = times when shrinkage is eating too many agents (need more scheduled). Green cells = times with excess capacity (could reduce scheduling). White cells = balanced.

### Understaffed Intervals Table

1. Click empty area below the heatmap > **Visualizations > Table**
2. Add columns: `vw_staffing[ts_start]`, `dim_channel[channel_name]`, `dim_queue[queue_name]`, `Scheduled Agents` measure, `Available Agents` measure, `Staffing Gap` measure
3. Click the `Staffing Gap` column header to sort ascending (most understaffed first)
4. In the **Filters** pane for this visual, add `Staffing Gap` filter > set to **is less than 0**

---

## Step 7: Report Page 4 — Service Analysis

**Business purpose:** Deep dive into service level performance. Where are customers waiting too long? Which queues are struggling? What time of day does service degrade?

Add a new page, rename to `Service Analysis`.

### Service Level Trend (top half)

1. **Visualizations > Line chart**
2. **X-axis**: `dim_time[date_key]`
3. **Y-axis**: `Avg Service Level` measure
4. Add a target reference line:
   - Click the **Analytics** pane (magnifying glass icon in Visualizations)
   - Click **Constant line > Add**
   - Value: `0.80`
   - Label: `Voice SLA Target (80%)`
   - Color: red, dashed line

### ASA by Queue (bottom-left)

Average Speed of Answer broken down by queue — shows which queues have the longest customer wait times.

1. **Visualizations > Clustered bar chart**
2. **Y-axis**: `dim_queue[queue_name]`
3. **X-axis**: `Avg ASA Seconds` measure
4. **Legend**: `dim_channel[channel_name]`
5. Sort descending (longest wait at top)

Email queues will show 0 or null ASA because email doesn't have real-time waiting — it's a throughput channel.

### Service Level by Hour (bottom-right)

Shows how service level varies throughout the day. Expect dips during peak hours (9-12, 14-17) when volume spikes.

1. **Visualizations > Column chart**
2. **X-axis**: `vw_contacts[hour]`
3. **Y-axis**: `Avg Service Level` measure
4. **Legend**: `dim_channel[channel_name]`
5. Add a constant line at 0.80 (same method as above)

---

## Step 8: Report Page 5 — Scenario Comparison

**Business purpose:** Compare the 7 staffing scenarios to understand cost-service tradeoffs. The Python pipeline simulated these scenarios:

| Scenario | What changes | Business question |
|---|---|---|
| Baseline | Nothing (reference point) | What does normal operations look like? |
| High demand (+10%) | 10% more contacts | Can we absorb a demand spike? |
| Low demand (-10%) | 10% fewer contacts | How much can we save if volume drops? |
| Shrinkage up (+5pp) | 5 percentage points more absenteeism | What if more agents call in sick? |
| Shrinkage down (-5pp) | 5 percentage points less absenteeism | What if we improve attendance? |
| Wage up (+10%) | 10% higher wages | What's the cost impact of raises? |
| Aggressive service (20% buffer) | 20% overstaffing buffer instead of 8% | What does "gold plated" service cost? |

Add a new page, rename to `Scenario Comparison`. Data source: `scenario_kpis` table.

### Scenario Slicer

1. **Visualizations > Slicer** > drag `scenario_kpis[scenario_name]` > set to **List**
2. Position at the top. Select all scenarios by default.

### Total Cost by Scenario (left)

1. **Visualizations > Clustered bar chart**
2. **Y-axis**: `scenario_kpis[scenario_name]`
3. **X-axis**: `scenario_kpis[planned_labor_cost]`, aggregation = **Sum**
4. **Format > Data labels**: toggle **On**
5. Sort descending by cost

### Avg Service Level by Scenario (right)

1. **Visualizations > Clustered bar chart**
2. **Y-axis**: `scenario_kpis[scenario_name]`
3. **X-axis**: `scenario_kpis[avg_service_level]`, aggregation = **Average**
4. **Format > Data labels**: toggle **On**, format as percentage
5. Sort descending

### Cost vs Service Scatter (bottom)

This is the key strategic visual — it plots each scenario as a dot showing the fundamental tradeoff: spending more on labor (X-axis) buys better service (Y-axis). The "Aggressive service" scenario will be top-right (high cost, high service). "Low demand" will be bottom-left.

1. **Visualizations > Scatter chart**
2. **X-axis**: `scenario_kpis[planned_labor_cost]`, aggregation = **Sum**
3. **Y-axis**: `scenario_kpis[avg_service_level]`, aggregation = **Average**
4. **Details**: `scenario_kpis[scenario_name]` (this creates one dot per scenario)
5. **Size**: `scenario_kpis[forecast_offered]`, aggregation = **Sum** (bigger bubble = more volume)
6. **Format > Category labels**: toggle **On** to label each dot with the scenario name

---

## Step 9: What-If Parameters (Optional)

What-If parameters let users dynamically adjust inputs without re-running the Python pipeline.

1. **Modeling > New Parameter > Numeric Range**
2. Create each:

| Name | Min | Max | Increment | Default |
|---|---|---|---|---|
| Demand Multiplier | 0.70 | 1.30 | 0.05 | 1.00 |
| Shrinkage Delta | -0.10 | 0.10 | 0.01 | 0.00 |
| Wage Multiplier | 0.80 | 1.30 | 0.05 | 1.00 |

3. Check **Add slicer to this page** for each
4. Create measures that use them:

**Adjusted Labor Cost** — Applies the wage multiplier to the base labor cost. A multiplier of 1.10 means a 10% wage increase:
```DAX
Adjusted Labor Cost = [Labor Cost] * [Wage Multiplier Value]
```

**Adjusted Demand** — Scales offered contacts by the demand multiplier:
```DAX
Adjusted Demand = [Offered Contacts] * [Demand Multiplier Value]
```

Use these adjusted measures in place of the originals on any visual to create interactive scenario modeling.

---

## Step 10: Formatting and Publishing

### Sync slicers across pages

1. Go to **View > Sync slicers**
2. Select the channel slicer on the Executive Summary page
3. Check the sync boxes for all other pages — now filtering by channel on any page filters all pages

### Apply a theme

1. **View > Themes** > pick a built-in theme or use the default

### Add page titles

1. **Insert > Text box** at the top of each page with the page name

### Save

**File > Save As** > name it `WFM_Forecast_Simulator.pbix`

### Publish (optional)

1. **Home > Publish** > select your Power BI Service workspace
2. In the service, configure a scheduled refresh if using the PostgreSQL connection

---

## Column Reference

| Source | Columns | Row Count |
|---|---|---|
| `vw_contacts` | ts_start, interval_minutes, channel_name, queue_name, offered_contacts, handled_contacts, abandoned_contacts, aht_seconds, asa_seconds, service_level, sla_threshold_seconds, date_key, year, month, day, dow, hour, minute | 60,480 |
| `vw_staffing` | ts_start, interval_minutes, channel_name, queue_name, agents_scheduled, agents_available, shrinkage_rate, cost_per_hour, date_key, year, month, day, dow, hour, minute | 60,480 |
| `dim_channel` | channel_id, channel_name, is_real_time | 3 |
| `dim_queue` | queue_id, channel_name, queue_name | 7 |
| `dim_time` | time_id, ts_start, date_key, year, month, day, dow, hour, minute | 8,640 |
| `scenario_kpis` (CSV) | scenario_id, scenario_name, date, channel, forecast_offered, planned_labor_cost, avg_service_level, avg_asa_seconds, avg_under_over | 588 |
| `model_quality` (CSV) | channel, queue, mape, rmse, holdout_days | 7 |

### Key domain values

| Field | Values | Meaning |
|---|---|---|
| `channel_name` | voice, chat, email | Contact channel |
| `is_real_time` | true (voice, chat), false (email) | Whether Erlang C queuing applies |
| `dow` | 0-6 | 0=Monday through 6=Sunday |
| `hour` | 0-23 | Hour of day |
| `interval_minutes` | 15 | Base interval granularity |
| `service_level` | 0.0-1.0 | Fraction of contacts answered within SLA threshold |
| `shrinkage_rate` | ~0.15-0.45 | Fraction of scheduled agents unavailable |
