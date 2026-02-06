# Technical Documentation: Workforce Demand & Staffing Forecast Simulator

## 1) Overview
This solution forecasts contact demand and simulates staffing strategies for a multi-channel call center (voice, chat, email). It is designed as a portfolio project that demonstrates end-to-end analytics: ingestion, ETL, modeling/forecasting, interpretation, and visualization.

## 2) High-level architecture
See `architecture/system_architecture.png` and `architecture/erd.png`.

Data flow:
1. **Sample data generator** creates interval-level historical demand & staffing data.
2. **ETL step** validates, cleans, normalizes, and builds analytical fact tables.
3. **Forecasting** produces baseline forecasts and scenario variants.
4. **Simulation** converts forecast demand into required staffing and estimates cost + service levels.
5. **BI layer** consumes Postgres views (or parquet exports) for dashboards.

## 3) Data model
### Dimensions
- `dim_time`: time grain aligned to the base interval (15 minutes) with date parts for slicing.
- `dim_channel`: voice/chat/email.
- `dim_queue`: skill/queue within channel.
- `dim_scenario`: scenario definition parameters.

### Facts
- `fact_contacts`: offered/handled/abandoned contacts with AHT, ASA, and service level.
- `fact_staffing`: scheduled and available agents, shrinkage, and hourly cost.
- `fact_forecast`: forecast outputs by timestamp/channel/queue.
- `fact_simulation`: scenario results (required agents, scheduled agents, cost, service level).

## 4) ETL details
### Inputs
- `data/demand_raw.csv`
- `data/staffing_raw.csv`

### Validations
- timestamp parsing, interval consistency
- non-negative counts and durations
- required columns present

### Cleaning & normalization
- enforce consistent channel/queue naming
- cast to correct types
- fill missing intervals with zeros where appropriate

### Aggregation support
The base grain is **15 minutes**, but the ETL writes rollups for:
- 30 minutes
- 60 minutes
- 8 hours
- 12 hours
- 24 hours

Rollups are stored at:
- `curated/aggregations/<minutes>m/fact_contacts.parquet`
- `curated/aggregations/<minutes>m/fact_staffing.parquet`

## 5) Forecasting approach
The default model is a fast and explainable **profile + trend** forecast:
- Builds a typical demand profile by day-of-week and time-of-day bucket
- Applies a trend factor based on recent daily totals

Why this is good for a demo:
- Works across many interval sizes
- Performs well on strongly seasonal call-center data
- Easy to explain to non-technical stakeholders

A holdout evaluation is computed for each series:
- **MAPE**
- **RMSE**

## 6) Staffing simulation
### Real-time channels (voice/chat)
Uses Erlang C to estimate:
- **ASA** (Average Speed of Answer)
- **Service level** (probability of answer within SLA threshold)

Staffing logic:
1. Convert contacts and AHT to offered load in Erlangs
2. Find minimum agents that meet target SLA
3. Convert required agents to scheduled agents using shrinkage and buffer

### Throughput channel (email)
Email is treated as a capacity pipeline:
- capacity = agents_available * interval_seconds / AHT
- service_level ≈ min(1, capacity / demand)

### Scenarios
The simulator runs baseline + adjustable scenarios, such as:
- demand up/down (multiplier)
- shrinkage up/down (percentage points)
- wage multiplier
- staffing buffer percent

Outputs include interval-level results and KPI rollups by day/channel.

## 7) Metrics
- Forecast Accuracy: MAPE, RMSE
- Labor cost variance: scenario cost vs baseline
- Service level attainment: percent of intervals meeting SLA
- Staffing gap: scheduled - required

## 8) Running locally
From the project folder:

```bash
pip install -r python/requirements.txt
python python/generate_sample_data.py --out_dir data --start 2025-09-01 --days 90 --seed 7
python python/etl_build_marts.py --in_dir data --out_dir data/curated
python python/forecast_and_simulate.py --in_dir data/curated --out_dir data/results --interval_minutes 60 --horizon_days 28
```

## 9) PostgreSQL loading
```bash
psql "$DATABASE_URL" -f sql/01_schema.sql
psql "$DATABASE_URL" -v data_dir='data/curated/postgres_load' -f sql/02_load_from_csv.sql
psql "$DATABASE_URL" -f sql/03_views.sql
```

## 10) BI usage
- Power BI: connect to Postgres schema `wfm` and use views `vw_contacts`, `vw_staffing`, `vw_forecast_latest`, `vw_scenario_kpis`.
- Tableau: same views; use extract for speed.

See `powerbi/report_design.md` and `tableau/dashboard_design.md` for build steps.
