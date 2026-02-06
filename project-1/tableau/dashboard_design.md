# Tableau Dashboard Design: Workforce Forecast Simulator

## Data Connection
Connect to PostgreSQL schema `wfm` and use:
- `vw_contacts`
- `vw_staffing`
- `vw_forecast_latest`
- `vw_scenario_kpis`

Tip: use an Extract for snappier filtering when interval granularity is 15 minutes.

## Key Calculations
### 1) Forecast Error
- `Abs Error` = ABS([offered_contacts] - [forecast_offered])
- `MAPE` (weighted) = SUM(ABS([offered_contacts] - [forecast_offered])) / SUM([offered_contacts])

### 2) Staffing Gap
- `Gap` = SUM([agents_scheduled]) - SUM([required_agents])
- `Overstaffed?` = IF [Gap] > 0 THEN 'Over' ELSE 'Under' END

### 3) SLA Attainment
- `SLA Met` = IF [service_level] >=
  IF [channel_name]='voice' THEN 0.80 ELSEIF [channel_name]='chat' THEN 0.75 ELSE 0.90 END
  THEN 1 ELSE 0 END

## Parameters (Interactive Controls)
Create parameters to mimic scenario levers:
- `Demand Multiplier` (float, 0.7 to 1.3)
- `Shrinkage Delta (pp)` (float, -0.1 to +0.1)
- `Wage Multiplier` (float, 0.8 to 1.3)
- `Staffing Buffer %` (float, 0 to 0.25)

If you want pure SQL-driven scenarios, use `vw_scenario_kpis` and expose `scenario_name` as a filter.

## Dashboard Pages
### 1) Executive Summary
- KPIs: Total Cost, SLA Attainment, Over/Understaffing, Forecast MAPE
- Filters: Date range, Interval, Channel, Scenario

### 2) Forecast vs Actual
- Line chart: actual offered vs forecast offered
- Small multiples by channel or queue
- Tooltip: error, AHT, ASA, SLA

### 3) Staffing Gap Heatmap
- Heatmap: hour-of-day vs day-of-week colored by `Gap`
- Drilldown: channel/queue

### 4) Cost vs Service Tradeoff
- Scatter: cost_total vs service_level (or SLA attainment)
- Color by scenario
- Size by volume (offered)

## Publishing Notes
- Publish with embedded credentials or use Tableau Server auth
- Use extracts for large 15m datasets
