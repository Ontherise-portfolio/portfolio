# Power BI Report Design: Workforce Forecast Simulator

## Data Connections
Preferred: PostgreSQL schema `wfm`.
Use these views (already shaped for BI):
- `wfm.vw_contacts`
- `wfm.vw_staffing`
- `wfm.vw_forecast_latest`
- `wfm.vw_scenario_kpis`

Fallback: use parquet/CSV outputs from `data/results/`.

## Data Model (Star schema)
- Fact tables: Contacts, Staffing, Forecast, Scenario KPIs
- Shared dimensions: Date/Time, Channel, Queue

Relationships
- `vw_contacts[ts_start]` (many) → `dim_time[ts_start]` (one)
- `vw_staffing[ts_start]` (many) → `dim_time[ts_start]` (one)
- `vw_forecast_latest[ts_start]` (many) → `dim_time[ts_start]` (one)
- `vw_scenario_kpis[date]` (many) → Date dimension (one)

## Core Measures (DAX)
### Volume
```DAX
Offered Contacts = SUM('vw_contacts'[offered_contacts])
Handled Contacts = SUM('vw_contacts'[handled_contacts])
Abandoned Contacts = SUM('vw_contacts'[abandoned_contacts])
Abandon Rate = DIVIDE([Abandoned Contacts], [Offered Contacts])
```

### Service
```DAX
Avg Service Level = AVERAGE('vw_contacts'[service_level])
Avg ASA Seconds = AVERAGE('vw_contacts'[asa_seconds])
SLA Attainment Rate =
AVERAGE('vw_scenario_kpis'[sla_attainment_rate])
```

### Staffing + Cost
```DAX
Scheduled Agents = SUM('vw_staffing'[agents_scheduled])
Available Agents = SUM('vw_staffing'[agents_available])
Labor Cost =
SUMX('vw_staffing',
    'vw_staffing'[agents_scheduled] * 'vw_staffing'[cost_per_hour] * ('vw_staffing'[interval_minutes] / 60.0)
)
```

### Forecast Accuracy (example)
Assumes you filter to a historical window where you have both actuals and forecast.
```DAX
Forecast Offered = SUM('vw_forecast_latest'[forecast_offered])
Actual Offered = SUM('vw_contacts'[offered_contacts])
Absolute Error = ABS([Forecast Offered] - [Actual Offered])
MAPE = DIVIDE([Absolute Error], [Actual Offered])
RMSE =
SQRT(AVERAGEX(VALUES('vw_contacts'[ts_start]),
    POWER([Forecast Offered] - [Actual Offered], 2)
))
```

## Report Pages
### 1) Executive Summary
- KPI cards: Offered, Labor Cost, Avg Service Level, SLA Attainment
- Trend: Offered vs Forecast (line)
- Cost vs Service: scatter by day (baseline vs scenario)

### 2) Forecast Quality
- MAPE, RMSE by channel and queue
- Forecast vs actual (small multiples)

### 3) Staffing Gap + Heatmaps
- Matrix heatmap: hour-of-day x day-of-week for staffing gaps
- Table: worst intervals (largest understaffing)

### 4) Scenario Comparison
- Slicer: scenario
- Bars: total cost, avg service level, SLA attainment
- Decomposition tree: drivers of cost variance

## Refresh + Parameters
- Use incremental refresh by `date` for large datasets.
- Optional What-If parameters to mimic scenario controls:
  - Demand multiplier
  - Shrinkage delta (pp)
  - Wage multiplier
  - Staffing buffer percent
