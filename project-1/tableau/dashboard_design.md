# Tableau Dashboard Design: Workforce Forecast Simulator

## Prerequisites

- Tableau Desktop or Tableau Public installed
- PostgreSQL `wfm` database loaded (steps 1-5 from the README)
- Scenario results CSV available at `data/results/kpi_summary_60m.csv`

---

## Step 1: Connect to PostgreSQL

1. Open **Tableau Desktop**
2. On the start screen, under **Connect > To a Server**, click **PostgreSQL**
   - If using Tableau Public (free), skip to the CSV fallback section below
3. Enter your connection details:
   - Server: `localhost`
   - Port: `5432`
   - Database: `wfm`
   - Username: `postgres`
   - Password: your PostgreSQL password
4. Click **Sign In**

### Add views as data sources

1. In the left panel, under **Schema**, select `wfm`
2. Under **Table**, search for and drag each of these onto the canvas:
   - `vw_contacts`
   - `vw_staffing`
   - `vw_scenario_kpis`
3. Each view should be added as its own data source (not joined together)
4. For best performance, click **Extract** (instead of Live) in the top-right of the data source tab, then click **Update Now**

### CSV fallback (Tableau Public or no Postgres)

If you don't have a PostgreSQL connection:

1. Click **Connect > To a File > Text File**
2. Navigate to `project-1/data/curated/postgres_load/` and load:
   - `fact_contacts.csv`
   - `fact_staffing.csv`
3. Also load the scenario results:
   - Navigate to `project-1/data/results/`
   - Load `kpi_summary_60m.csv`

### Add the scenario KPI CSV

Whether using Postgres or not, you'll need the scenario results CSV:

1. Click **Data > New Data Source > Text File**
2. Navigate to `project-1/data/results/kpi_summary_60m.csv`
3. Click **Open**
4. Tableau will auto-detect columns. Verify that `date` is recognized as a Date type
5. Rename this data source to `Scenario KPIs` (right-click the tab at the top of the data source pane)

---

## Step 2: Create Calculated Fields

After connecting, go to a new worksheet. For each data source, create these calculated fields.

### On `vw_contacts` (or `fact_contacts`)

Right-click in the **Data** pane (left sidebar) > **Create Calculated Field** for each:

**Abandon Rate:**
```
SUM([Abandoned Contacts]) / SUM([Offered Contacts])
```

**SLA Met (per row):**
```
IF [Service Level] >=
  (IF [Channel Name] = 'voice' THEN 0.80
   ELSEIF [Channel Name] = 'chat' THEN 0.75
   ELSE 0.90 END)
THEN 1 ELSE 0
END
```

**SLA Attainment Rate:**
```
AVG([SLA Met (per row)])
```

### On `vw_staffing` (or `fact_staffing`)

**Labor Cost (per row):**
```
[Agents Scheduled] * [Cost Per Hour] * ([Interval Minutes] / 60.0)
```

**Staffing Gap:**
```
[Agents Scheduled] - [Agents Available]
```

**Overstaffed?:**
```
IF [Staffing Gap] > 0 THEN 'Over' ELSE 'Under' END
```

### On `Scenario KPIs`

No calculated fields needed — columns are pre-aggregated from the Python pipeline.

---

## Step 3: Build Dashboard 1 — Executive Summary

### Create the KPI text sheet

1. Click **Worksheet > New Worksheet**, rename it to `KPI Cards`
2. Set the data source to `vw_contacts`
3. Drag `SUM(Offered Contacts)` to the **Text** shelf on the Marks card
4. Drag `SUM(Handled Contacts)` to the **Text** shelf
5. Drag `AVG(Service Level)` to the **Text** shelf
6. Drag `Abandon Rate` (calculated field) to the **Text** shelf
7. Click the **Text** mark, then click the **...** button to format the layout:
   - Arrange the four values with labels, e.g.:
     ```
     Offered: <SUM(Offered Contacts)>    Handled: <SUM(Handled Contacts)>
     Avg SLA: <AVG(Service Level)>       Abandon Rate: <AGG(Abandon Rate)>
     ```
8. Format `AVG(Service Level)` and `Abandon Rate` as percentages:
   - Right-click the field on the Marks card > **Format** > Numbers > **Percentage**

### Create the volume trend line chart

1. Create a new worksheet, rename to `Volume Trend`
2. Data source: `vw_contacts`
3. Drag `Date Key` to **Columns** (it will become a date hierarchy — click the `+` to expand to the Day level, or right-click and select **Exact Date**)
4. Drag `SUM(Offered Contacts)` to **Rows**
5. Drag `SUM(Handled Contacts)` to **Rows** (next to the first pill — this creates a dual axis)
6. Right-click the second Y-axis > **Synchronize Axis**
7. On the **Marks** card for both measures, set mark type to **Line**
8. Add color distinction: click the **Color** button on each Marks card and choose different colors

### Create the channel breakdown bar chart

1. Create a new worksheet, rename to `Channel Breakdown`
2. Data source: `vw_contacts`
3. Drag `Channel Name` to **Rows**
4. Drag `SUM(Offered Contacts)` to **Columns**
5. Drag `Channel Name` to **Color** on the Marks card
6. Sort descending by clicking the sort icon in the toolbar

### Assemble the dashboard

1. Click **Dashboard > New Dashboard**
2. Rename to `Executive Summary`
3. Set the dashboard size: **Dashboard** pane (left) > **Size** > select **Automatic** or **Fixed (1200 x 800)**
4. Drag the `KPI Cards` sheet onto the top of the dashboard canvas
5. Drag the `Volume Trend` sheet below the KPI cards (left half)
6. Drag the `Channel Breakdown` sheet to the right of the trend

### Add filters

1. On the dashboard, click the `Volume Trend` sheet
2. Click the filter icon (funnel) in the top-right corner of the sheet
3. Select `Channel Name` — this adds an interactive filter
4. Right-click the filter > **Apply to Worksheets > All Using This Data Source**
5. Repeat for `Date Key` to add a date range filter

---

## Step 4: Build Dashboard 2 — Staffing Gap Heatmap

### Create the heatmap worksheet

1. Create a new worksheet, rename to `Staffing Heatmap`
2. Data source: `vw_staffing`
3. Drag `Dow` to **Rows**
4. Drag `Hour` to **Columns**
5. Drag `AVG(Staffing Gap)` (calculated field) to **Color** on the Marks card
6. Set the mark type to **Square** (dropdown at the top of the Marks card)
7. Click **Color** > **Edit Colors**:
   - Select a **Red-Green Diverging** palette
   - Check **Stepped Color** with 5 steps
   - Set the center to `0`
   - Click **OK**
8. Drag `AVG(Staffing Gap)` to **Label** on the Marks card to show values in each cell
9. Right-click the `Dow` axis > **Edit Alias** to rename 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun

### Create the understaffed intervals table

1. Create a new worksheet, rename to `Understaffed Intervals`
2. Data source: `vw_staffing`
3. Change the view to a text table: click **Show Me** (top right) > select **Text table**
4. Drag these to **Rows**: `Ts Start`, `Channel Name`, `Queue Name`
5. Drag `SUM(Agents Scheduled)`, `SUM(Agents Available)`, `SUM(Staffing Gap)` to the **Text** shelf
6. Right-click `SUM(Staffing Gap)` on the Rows shelf > **Sort** > **Ascending**
7. Add a filter: drag `Staffing Gap` to the **Filters** shelf > select **Range** > set max to `0` to show only understaffed rows

### Assemble the dashboard

1. Click **Dashboard > New Dashboard**, rename to `Staffing Heatmap`
2. Drag `Staffing Heatmap` sheet onto the top (takes up most of the space)
3. Drag `Understaffed Intervals` sheet below it
4. Add a channel filter (same method as Step 3)

---

## Step 5: Build Dashboard 3 — Service Analysis

### Create the service level trend

1. Create a new worksheet, rename to `SLA Trend`
2. Data source: `vw_contacts`
3. Drag `Date Key` to **Columns** (set to exact date)
4. Drag `AVG(Service Level)` to **Rows**
5. Set mark type to **Line**
6. Add a reference line for the SLA target:
   - Right-click the Y-axis > **Add Reference Line**
   - Set **Value** to **Constant** = `0.80`
   - Set **Label** to **Custom** = `Target SLA (80%)`
   - Set **Line** color to red, dashed
   - Click **OK**

### Create the ASA by queue chart

1. Create a new worksheet, rename to `ASA by Queue`
2. Data source: `vw_contacts`
3. Drag `Queue Name` to **Rows**
4. Drag `AVG(Asa Seconds)` to **Columns**
5. Drag `Channel Name` to **Color** on the Marks card
6. Sort descending by AVG(Asa Seconds)

### Create service level by hour

1. Create a new worksheet, rename to `SLA by Hour`
2. Data source: `vw_contacts`
3. Drag `Hour` to **Columns** (right-click > **Dimension** to keep it discrete)
4. Drag `AVG(Service Level)` to **Rows**
5. Drag `Channel Name` to **Color** on the Marks card
6. Set mark type to **Bar**
7. Add the 0.80 reference line (same method as SLA Trend)

### Assemble the dashboard

1. Click **Dashboard > New Dashboard**, rename to `Service Analysis`
2. Drag `SLA Trend` across the top
3. Drag `ASA by Queue` to the bottom-left
4. Drag `SLA by Hour` to the bottom-right
5. Add channel and date filters

---

## Step 6: Build Dashboard 4 — Scenario Comparison

### Create scenario cost bar chart

1. Create a new worksheet, rename to `Scenario Cost`
2. Data source: `Scenario KPIs` (the CSV)
3. Drag `Scenario Name` to **Rows**
4. Drag `SUM(Planned Labor Cost)` to **Columns**
5. Drag `Scenario Name` to **Color** on the Marks card
6. Sort descending by cost

### Create scenario service level bar chart

1. Create a new worksheet, rename to `Scenario SLA`
2. Data source: `Scenario KPIs`
3. Drag `Scenario Name` to **Rows**
4. Drag `AVG(Avg Service Level)` to **Columns**
5. Format as percentage: right-click the axis > **Format** > **Numbers** > **Percentage**
6. Sort descending

### Create cost vs service scatter

1. Create a new worksheet, rename to `Cost vs Service`
2. Data source: `Scenario KPIs`
3. Drag `SUM(Planned Labor Cost)` to **Columns**
4. Drag `AVG(Avg Service Level)` to **Rows**
5. Drag `Scenario Name` to **Detail** on the Marks card
6. Drag `Scenario Name` to **Color** on the Marks card
7. Drag `SUM(Forecast Offered)` to **Size** on the Marks card (bubble size = volume)
8. Set mark type to **Circle**
9. Click **Label** > check **Show mark labels** > select `Scenario Name`

### Assemble the dashboard

1. Click **Dashboard > New Dashboard**, rename to `Scenario Comparison`
2. Drag `Scenario Cost` to the top-left
3. Drag `Scenario SLA` to the top-right
4. Drag `Cost vs Service` across the bottom
5. Add a filter on `Scenario Name`:
   - Click the `Scenario Cost` sheet on the dashboard
   - Click the filter icon > select `Scenario Name`
   - Right-click the filter > **Apply to Worksheets > All Using This Data Source**

---

## Step 7: Add Interactive Parameters (Optional)

Parameters let users adjust scenario inputs dynamically.

### Create parameters

For each parameter: right-click in the **Data** pane > **Create Parameter**

| Name               | Data type | Range       | Step | Default |
|--------------------|-----------|-------------|------|---------|
| Demand Multiplier  | Float     | 0.70 – 1.30| 0.05 | 1.00    |
| Shrinkage Delta    | Float     | -0.10 – 0.10| 0.01| 0.00    |
| Wage Multiplier    | Float     | 0.80 – 1.30| 0.05 | 1.00    |
| Staffing Buffer %  | Float     | 0.00 – 0.25| 0.01 | 0.08    |

### Show parameter controls

1. Right-click each parameter in the Data pane > **Show Parameter**
2. The sliders will appear on the right side of any worksheet

### Create calculated fields using parameters

On `vw_contacts`:

**Adjusted Demand:**
```
SUM([Offered Contacts]) * [Demand Multiplier]
```

On `vw_staffing`:

**Adjusted Labor Cost:**
```
SUM([Labor Cost (per row)]) * [Wage Multiplier] * (1 + [Staffing Buffer %])
```

Use these adjusted measures in place of the originals to make dashboards interactive.

---

## Step 8: Format and Publish

### Apply consistent formatting

1. For each dashboard, click **Dashboard > Format**:
   - Set **Dashboard Shading** to a light background color
   - Set consistent fonts across all sheets (e.g., Tableau Regular, 10pt)
2. Add titles: drag a **Text** object from the dashboard pane onto the top of each dashboard
3. Add a **Navigation** object if you want page-to-page links:
   - From the Dashboard pane, drag **Navigation** onto the dashboard
   - Point it to another dashboard

### Save the workbook

1. **File > Save As** — name the file `WFM_Forecast_Simulator.twbx`
   - `.twbx` packages the data extracts with the workbook (portable)
   - `.twb` saves just the workbook (requires live data source access)

### Publish to Tableau Server / Tableau Public

**Tableau Public (free):**
1. **Server > Tableau Public > Save to Tableau Public As**
2. Sign in with your Tableau Public account
3. Name the workbook and click **Save**

**Tableau Server / Tableau Cloud:**
1. **Server > Sign In** — enter your server URL and credentials
2. **Server > Publish Workbook**
3. Select the project/folder
4. Choose **Embed Credentials** for the PostgreSQL connection (or prompt users)
5. Click **Publish**

---

## Column Reference

These are the columns available in each data source:

| Source                | Columns                                                                                              |
|-----------------------|------------------------------------------------------------------------------------------------------|
| `vw_contacts`         | ts_start, interval_minutes, channel_name, queue_name, offered_contacts, handled_contacts, abandoned_contacts, aht_seconds, asa_seconds, service_level, sla_threshold_seconds, date_key, year, month, day, dow, hour, minute |
| `vw_staffing`         | ts_start, interval_minutes, channel_name, queue_name, agents_scheduled, agents_available, shrinkage_rate, cost_per_hour, date_key, year, month, day, dow, hour, minute |
| `vw_scenario_kpis`    | scenario_name, interval_minutes, date_key, channel_name, required_agents_sum, scheduled_agents_sum, cost_total_sum, service_level_avg, sla_attainment_rate |
| `kpi_summary_60m.csv` | scenario_id, scenario_name, date, channel, forecast_offered, planned_labor_cost, avg_service_level, avg_asa_seconds, avg_under_over |
| `dim_channel`         | channel_id, channel_name, is_real_time                                                               |
| `dim_queue`           | queue_id, channel_name, queue_name                                                                   |
| `dim_time`            | time_id, ts_start, date_key, year, month, day, dow, hour, minute                                     |
