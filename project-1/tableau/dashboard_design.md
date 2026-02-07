# Tableau Dashboard: Workforce Forecast Simulator

## Prerequisites

- Tableau Desktop or Tableau Public installed
- PostgreSQL `wfm` database loaded (schema + data + views from steps 1-5)
- CSV files in `data/results/`: `kpi_summary_60m.csv`, `model_quality_60m.csv`

---

## Step 1: Connect to Data

### Option A: PostgreSQL (Tableau Desktop)

1. Open **Tableau Desktop**
2. Under **Connect > To a Server**, click **PostgreSQL**
3. Server: `localhost`, Port: `5432`, Database: `wfm`, Username: `postgres`, Password: your password
4. Click **Sign In**
5. In the left panel, set **Schema** to `wfm`
6. Drag `vw_contacts` onto the canvas — this becomes your first data source
7. Click **Update Now** to preview the data. You should see ~60,480 rows with columns like `ts_start`, `channel_name`, `offered_contacts`, `service_level`, etc.
8. Switch to **Extract** (top-right radio button) for faster performance, then click **Update Now**

### Repeat for staffing data

1. Click **Data > New Data Source > PostgreSQL** (same connection)
2. Drag `vw_staffing` onto the canvas
3. Switch to **Extract**

### Option B: CSV (Tableau Public or no Postgres)

Tableau Public can't connect to databases. Use the CSVs instead:

1. **Connect > To a File > Text File**
2. Load `data/curated/postgres_load/fact_contacts.csv` — rename the data source to `Contacts`
3. **Data > New Data Source > Text File** > load `data/curated/postgres_load/fact_staffing.csv` — rename to `Staffing`

The CSV columns use the same names as the Postgres views (`ts_start`, `channel_name`, `queue_name`, etc.) but lack the time dimension fields (`date_key`, `dow`, `hour`). You'll create those as calculated fields in Step 2.

### Add scenario and model quality CSVs

For both PostgreSQL and CSV paths:

1. **Data > New Data Source > Text File**
2. Load `data/results/kpi_summary_60m.csv` — rename to `Scenario KPIs`
3. **Data > New Data Source > Text File**
4. Load `data/results/model_quality_60m.csv` — rename to `Model Quality`

### Verify data types

For each data source, check the data types in the data source tab (click the icon above each column):
- `ts_start`: should be **Date & Time**
- `date_key` / `date`: should be **Date**
- All numeric columns (offered_contacts, service_level, etc.): should be **Number (whole)** or **Number (decimal)**
- `channel_name`, `queue_name`, `scenario_name`: should be **String**

If any type is wrong, click the icon above the column and change it.

---

## Step 2: Calculated Fields

Go to a new worksheet. For each data source, right-click in the **Data** pane > **Create Calculated Field**.

### On `vw_contacts` (or `Contacts` CSV)

**Abandon Rate** — Fraction of contacts that abandoned before being answered. In WFM, >5% is a warning, >10% is critical:
```
SUM([Abandoned Contacts]) / SUM([Offered Contacts])
```
*Why SUM/SUM?* This gives a weighted average across all rows in the filter context. Simply dividing the two columns row-by-row would give per-interval rates that don't aggregate correctly.

**SLA Met** — Binary flag: did this interval meet its channel-specific SLA target? Voice must hit 80%, chat 75%, email 90%. These thresholds come from the SLA agreements (voice: 80% in 20s, chat: 75% in 30s, email: 90% in 24h):
```
IF [Service Level] >=
    (IF [Channel Name] = 'voice' THEN 0.80
     ELSEIF [Channel Name] = 'chat' THEN 0.75
     ELSE 0.90 END)
THEN 1 ELSE 0
END
```

**SLA Attainment Rate** — What proportion of intervals met their SLA target. Use as `AVG([SLA Met])` in visuals:
```
AVG([SLA Met])
```

**Day of Week** (only needed for CSV path — the Postgres view already has `dow`):
```
DATEPART('weekday', [Ts Start]) - 2
```
*Note:* Tableau's `weekday` returns 1=Sunday. This formula converts to 0=Monday to match the Postgres `dow` column.

**Hour** (only needed for CSV path):
```
DATEPART('hour', [Ts Start])
```

### On `vw_staffing` (or `Staffing` CSV)

**Labor Cost** — Total labor cost per interval. The formula multiplies agents by their hourly rate, then pro-rates for the 15-minute interval (15/60 = 0.25 hours):
```
[Agents Scheduled] * [Cost Per Hour] * ([Interval Minutes] / 60.0)
```
*Why per-row?* This is a row-level calculation. When Tableau aggregates, use `SUM([Labor Cost])` to get totals.

**Staffing Gap** — How many more agents are scheduled than available. Positive = overstaffed (excess capacity), negative = understaffed (shrinkage ate too many agents):
```
[Agents Scheduled] - [Agents Available]
```

**Overstaffed?** — Categorizes each interval as over or under staffed. Useful for coloring visuals:
```
IF [Staffing Gap] > 0 THEN 'Over' ELSE 'Under' END
```

### On `Scenario KPIs`

No calculated fields needed. The CSV contains pre-aggregated daily KPIs per scenario per channel from the Python simulation pipeline.

---

## Step 3: Dashboard 1 — Executive Summary

**Business purpose:** Single-page overview for leadership showing contact center health: volume, cost, service quality, and trends over the 90-day simulation period.

### Worksheet: KPI Cards

1. New worksheet, rename to `KPI Cards`
2. Data source: `vw_contacts`
3. Drag `SUM(Offered Contacts)` to **Text** on the Marks card
4. Drag `SUM(Handled Contacts)` to **Text**
5. Drag `AVG(Service Level)` to **Text**
6. Drag `AGG(Abandon Rate)` to **Text**
7. Click the **Text** button on the Marks card > click the **...** to open the editor
8. Format the layout:
   ```
   Offered: <SUM(Offered Contacts)>    Handled: <SUM(Handled Contacts)>
   Avg SLA: <AVG(Service Level)>       Abandon Rate: <AGG(Abandon Rate)>
   ```
9. Format percentages: right-click `AVG(Service Level)` on the Marks card > **Format** > **Numbers** > **Percentage**, 1 decimal
10. Repeat for Abandon Rate

### Worksheet: Volume Trend

Shows daily contact volume. Look for the weekly cycle (weekend dips) and the +0.08%/day upward trend baked into the synthetic data.

1. New worksheet, rename to `Volume Trend`
2. Data source: `vw_contacts`
3. Drag `Date Key` to **Columns** — right-click the pill > select **Exact Date** (not the YEAR hierarchy)
4. Drag `SUM(Offered Contacts)` to **Rows**
5. Drag `SUM(Handled Contacts)` to **Rows** (this creates a second axis)
6. Right-click the right Y-axis > **Synchronize Axis**
7. On the **Marks** card, ensure both are set to **Line**
8. Click **Color** on each Marks card: set Offered = blue, Handled = green

### Worksheet: Channel Breakdown

1. New worksheet, rename to `Channel Breakdown`
2. Data source: `vw_contacts`
3. Drag `Channel Name` to **Rows**
4. Drag `SUM(Offered Contacts)` to **Columns**
5. Drag `Channel Name` to **Color** on Marks card
6. Click the sort icon (toolbar) to sort descending

Voice should show the highest volume (~41 contacts per 15-min base rate), followed by chat (~18), then email (~10).

### Assemble the dashboard

1. **Dashboard > New Dashboard**, rename to `Executive Summary`
2. Set size: **Dashboard** pane > **Size** > **Automatic** or **Fixed (1200 x 800)**
3. Drag `KPI Cards` to the top
4. Drag `Volume Trend` to the left half below
5. Drag `Channel Breakdown` to the right half below

### Add filters

1. On the dashboard, click the `Volume Trend` sheet > click the **funnel icon** (top-right of the sheet)
2. Select `Channel Name` — an interactive filter appears
3. Right-click the filter > **Apply to Worksheets > All Using This Data Source**
4. Repeat: click `Volume Trend` > funnel > select `Date Key` for a date range filter

---

## Step 4: Dashboard 2 — Forecast Quality

**Business purpose:** Evaluate forecast model accuracy per channel and queue. Poor forecasts directly cause staffing errors — over-forecasting wastes labor budget, under-forecasting misses SLA.

### Worksheet: MAPE by Queue

MAPE (Mean Absolute Percentage Error) measures the average % deviation between forecasted and actual demand. Under 20% is good for WFM; under 10% is excellent.

1. New worksheet, rename to `MAPE by Queue`
2. Data source: `Model Quality`
3. Drag `Queue` to **Rows**
4. Drag `Mape` to **Columns** — right-click the pill > **Dimension** (don't aggregate, there's one row per queue)
5. Drag `Channel` to **Color** on Marks card
6. **Format > Data labels**: right-click axis > **Format** > **Numbers** > **Percentage** if values are in decimal form, otherwise **Number (Standard)**

### Worksheet: RMSE by Queue

RMSE (Root Mean Squared Error) penalizes large forecast errors more than MAPE (due to squaring). A model with low MAPE but high RMSE occasionally makes large mistakes.

1. New worksheet, rename to `RMSE by Queue`
2. Data source: `Model Quality`
3. Drag `Queue` to **Rows**
4. Drag `Rmse` to **Columns** — right-click > **Dimension**
5. Drag `Channel` to **Color**

### Assemble the dashboard

1. **Dashboard > New Dashboard**, rename to `Forecast Quality`
2. Drag `MAPE by Queue` to the left half
3. Drag `RMSE by Queue` to the right half
4. Add a **Text** object at the top with interpretation guidance:
   ```
   MAPE: Average % error. <10% excellent, 10-20% good, >50% poor
   RMSE: Penalizes big misses. Compare across queues to find problem areas.
   Holdout: 14 days withheld from training for evaluation.
   ```

---

## Step 5: Dashboard 3 — Staffing Gap Heatmap

**Business purpose:** The most actionable dashboard for WFM planners. Shows exactly which day-of-week + hour-of-day combinations are overstaffed or understaffed, so planners can adjust shift schedules.

### Worksheet: Heatmap

1. New worksheet, rename to `Staffing Heatmap`
2. Data source: `vw_staffing`
3. Drag `Dow` to **Rows** — right-click > **Dimension** (prevents aggregation)
4. Drag `Hour` to **Columns** — right-click > **Dimension**
5. Drag `AVG(Staffing Gap)` to **Color** on Marks card
6. Set mark type to **Square** (dropdown at top of Marks card)
7. Click **Color > Edit Colors**:
   - Palette: **Red-Green Diverging**
   - Check **Stepped Color**, 5 steps
   - Click **Advanced** > check **Center**: set to `0`
   - This makes red=understaffed, white=balanced, green=overstaffed
8. Drag `AVG(Staffing Gap)` to **Label** to show values in cells
9. Right-click each `Dow` value on the axis > **Edit Alias**:
   - 0 → Mon, 1 → Tue, 2 → Wed, 3 → Thu, 4 → Fri, 5 → Sat, 6 → Sun

**Reading the heatmap:** Red squares indicate times where shrinkage is causing understaffing — schedule more agents for those slots. Green squares indicate excess capacity — reduce scheduling to save labor cost.

### Worksheet: Understaffed Intervals

A detail table showing the worst-staffed specific intervals.

1. New worksheet, rename to `Understaffed Intervals`
2. Data source: `vw_staffing`
3. Click **Show Me** (top-right) > select **Text table**
4. Drag to **Rows**: `Ts Start`, `Channel Name`, `Queue Name`
5. Drag to **Text** on Marks: `SUM(Agents Scheduled)`, `SUM(Agents Available)`, `SUM(Staffing Gap)`
6. Add a filter: drag `Staffing Gap` to **Filters** > **Range of values** > set max to `0`
7. Right-click `SUM(Staffing Gap)` column header > **Sort > Ascending** (worst understaffing first)

### Assemble the dashboard

1. **Dashboard > New Dashboard**, rename to `Staffing Heatmap`
2. Drag `Staffing Heatmap` to the top (2/3 of the space)
3. Drag `Understaffed Intervals` to the bottom (1/3)
4. Add a channel filter (funnel icon on the heatmap sheet > Channel Name)

---

## Step 6: Dashboard 4 — Service Analysis

**Business purpose:** Deep dive into service level performance — when and where are customers waiting too long? Which queues are the bottleneck?

### Worksheet: SLA Trend

Service level over time. The SLA target line helps identify days where performance degraded.

1. New worksheet, rename to `SLA Trend`
2. Data source: `vw_contacts`
3. Drag `Date Key` to **Columns** (right-click > **Exact Date**)
4. Drag `AVG(Service Level)` to **Rows**
5. Set mark type to **Line**
6. Add a reference line:
   - Right-click the Y-axis > **Add Reference Line**
   - **Value**: Constant = `0.80`
   - **Label**: Custom = `Voice SLA Target (80%)`
   - **Line**: color = red, style = dashed
   - Click **OK**

### Worksheet: ASA by Queue

Average Speed of Answer per queue. Longer ASA = longer customer wait. Only applies to real-time channels (voice, chat) — email shows 0 because it's a throughput channel with no real-time queuing.

1. New worksheet, rename to `ASA by Queue`
2. Data source: `vw_contacts`
3. Drag `Queue Name` to **Rows**
4. Drag `AVG(Asa Seconds)` to **Columns**
5. Drag `Channel Name` to **Color**
6. Sort descending (longest wait at top)

### Worksheet: SLA by Hour

Shows service level broken down by hour of day. Expect dips during peak hours (9am-12pm, 2pm-5pm) when contact volume spikes but staffing can't keep up.

1. New worksheet, rename to `SLA by Hour`
2. Data source: `vw_contacts`
3. Drag `Hour` to **Columns** — right-click > **Dimension** (keeps it discrete 0-23)
4. Drag `AVG(Service Level)` to **Rows**
5. Drag `Channel Name` to **Color**
6. Set mark type to **Bar**
7. Add a reference line at 0.80 (same method as SLA Trend)

### Assemble the dashboard

1. **Dashboard > New Dashboard**, rename to `Service Analysis`
2. Drag `SLA Trend` across the top
3. Drag `ASA by Queue` to bottom-left
4. Drag `SLA by Hour` to bottom-right
5. Add channel and date filters

---

## Step 7: Dashboard 5 — Scenario Comparison

**Business purpose:** Compare the 7 staffing scenarios to quantify the cost-service tradeoff. The Python pipeline simulated:

| Scenario | What changes | Business question |
|---|---|---|
| Baseline | Nothing | What does normal look like? |
| High demand (+10%) | +10% contacts | Can we handle a demand surge? |
| Low demand (-10%) | -10% contacts | How much do we save if volume dips? |
| Shrinkage up (+5pp) | +5pp absenteeism | What if attendance worsens? |
| Shrinkage down (-5pp) | -5pp absenteeism | What if we improve attendance? |
| Wage up (+10%) | +10% labor cost | What's the budget impact of raises? |
| Aggressive service (20% buffer) | 20% overstaffing | What does premium service cost? |

### Worksheet: Scenario Cost

1. New worksheet, rename to `Scenario Cost`
2. Data source: `Scenario KPIs`
3. Drag `Scenario Name` to **Rows**
4. Drag `SUM(Planned Labor Cost)` to **Columns**
5. Drag `Scenario Name` to **Color**
6. Sort descending
7. Right-click axis > **Format** > **Numbers** > **Currency**

### Worksheet: Scenario SLA

1. New worksheet, rename to `Scenario SLA`
2. Data source: `Scenario KPIs`
3. Drag `Scenario Name` to **Rows**
4. Drag `AVG(Avg Service Level)` to **Columns**
5. Right-click axis > **Format** > **Numbers** > **Percentage**
6. Sort descending

### Worksheet: Cost vs Service Scatter

The key strategic visual. Each scenario is a dot: X = total cost, Y = average service level. This directly visualizes the tradeoff — spending more (right) buys better service (up). "Aggressive" will be top-right, "Low demand" bottom-left.

1. New worksheet, rename to `Cost vs Service`
2. Data source: `Scenario KPIs`
3. Drag `SUM(Planned Labor Cost)` to **Columns**
4. Drag `AVG(Avg Service Level)` to **Rows**
5. Drag `Scenario Name` to **Detail** on Marks (creates one dot per scenario)
6. Drag `Scenario Name` to **Color**
7. Drag `SUM(Forecast Offered)` to **Size** (bigger bubble = more volume)
8. Set mark type to **Circle**
9. Click **Label** > check **Show mark labels** > add `Scenario Name`

### Assemble the dashboard

1. **Dashboard > New Dashboard**, rename to `Scenario Comparison`
2. Drag `Scenario Cost` to top-left
3. Drag `Scenario SLA` to top-right
4. Drag `Cost vs Service` across the bottom
5. Add a filter: click `Scenario Cost` on the dashboard > funnel icon > `Scenario Name`
6. Right-click the filter > **Apply to Worksheets > All Using This Data Source**

---

## Step 8: Interactive Parameters (Optional)

Parameters let users adjust scenario inputs dynamically with sliders.

### Create parameters

Right-click in the **Data** pane > **Create Parameter** for each:

| Name | Data type | Allowable values | Range | Step | Default |
|---|---|---|---|---|---|
| Demand Multiplier | Float | Range | 0.70 – 1.30 | 0.05 | 1.00 |
| Shrinkage Delta | Float | Range | -0.10 – 0.10 | 0.01 | 0.00 |
| Wage Multiplier | Float | Range | 0.80 – 1.30 | 0.05 | 1.00 |
| Staffing Buffer % | Float | Range | 0.00 – 0.25 | 0.01 | 0.08 |

### Show parameter controls

Right-click each parameter > **Show Parameter**. Sliders appear on the right side of the worksheet.

### Create calculated fields that use the parameters

On `vw_contacts`:

**Adjusted Demand** — Multiplies actual demand by the parameter. At 1.10, this simulates a 10% demand increase:
```
SUM([Offered Contacts]) * [Demand Multiplier]
```

On `vw_staffing`:

**Adjusted Labor Cost** — Applies wage multiplier and staffing buffer to the base cost:
```
SUM([Labor Cost]) * [Wage Multiplier] * (1 + [Staffing Buffer %])
```

Replace the original measures with these adjusted versions in any visual to make it respond to parameter sliders.

---

## Step 9: Formatting and Publishing

### Format dashboards

1. For each dashboard: **Dashboard > Format**
   - Set **Dashboard Shading** to a light background
   - Set consistent fonts (Tableau Regular, 10pt)
2. Add titles: drag a **Text** object from the Dashboard pane onto the top of each dashboard
3. Add navigation between dashboards: drag a **Navigation** object > point to another dashboard

### Save

**File > Save As** > `WFM_Forecast_Simulator.twbx`
- `.twbx` = packaged workbook (includes data extracts — portable, shareable)
- `.twb` = workbook only (requires live data source access)

### Publish

**Tableau Public (free):**
1. **Server > Tableau Public > Save to Tableau Public As**
2. Sign in, name the workbook, click **Save**

**Tableau Server / Cloud:**
1. **Server > Sign In** > enter server URL and credentials
2. **Server > Publish Workbook** > select project > **Publish**
3. Choose **Embed Credentials** for PostgreSQL

---

## Column Reference

| Source | Columns | Row Count |
|---|---|---|
| `vw_contacts` | ts_start, interval_minutes, channel_name, queue_name, offered_contacts, handled_contacts, abandoned_contacts, aht_seconds, asa_seconds, service_level, sla_threshold_seconds, date_key, year, month, day, dow, hour, minute | 60,480 |
| `vw_staffing` | ts_start, interval_minutes, channel_name, queue_name, agents_scheduled, agents_available, shrinkage_rate, cost_per_hour, date_key, year, month, day, dow, hour, minute | 60,480 |
| `Scenario KPIs` (CSV) | scenario_id, scenario_name, date, channel, forecast_offered, planned_labor_cost, avg_service_level, avg_asa_seconds, avg_under_over | 588 |
| `Model Quality` (CSV) | channel, queue, mape, rmse, holdout_days | 7 |

### Key domain values

| Field | Values | Meaning |
|---|---|---|
| `channel_name` | voice, chat, email | Contact channel |
| `dow` | 0-6 | 0=Monday through 6=Sunday |
| `hour` | 0-23 | Hour of day |
| `interval_minutes` | 15 | Base interval granularity |
| `service_level` | 0.0-1.0 | Fraction of contacts answered within SLA threshold |
| `shrinkage_rate` | ~0.15-0.45 | Fraction of scheduled agents unavailable |
| SLA targets | voice=0.80, chat=0.75, email=0.90 | Channel-specific service level commitments |
