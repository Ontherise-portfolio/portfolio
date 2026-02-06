# Project 1: Workforce Demand & Staffing Forecast Simulator (Call Center)

This project forecasts contact demand (phones, chats, email), runs staffing simulations, and quantifies cost vs service tradeoffs.

## Included
- Sample data (CSVs) plus a Python generator
- Python: ETL, forecasting, scenario simulation, and metrics (MAPE/RMSE, cost variance, service level attainment)
- PostgreSQL: schema, load scripts, and analytical views
- Power BI: model + DAX measures + report layout plan
- Tableau: calculations + parameters + dashboard plan
- Diagrams: architecture + ERD

## Quick start
1) Create a Python environment and install dependencies:

```bash
pip install -r python/requirements.txt
```

2) Generate sample data (base interval = 15 minutes):

```bash
python python/generate_sample_data.py --out_dir data --start 2025-09-01 --days 90 --seed 7
```

3) Build the analytics layer (parquet outputs + optional Postgres load CSVs):

```bash
python python/etl_build_marts.py --in_dir data --out_dir data/curated
```

4) Forecast demand and run staffing scenarios:

```bash
python python/forecast_and_simulate.py --in_dir data/curated --out_dir data/results --horizon_days 28
```

5) Load into Postgres (optional):

```bash
psql "$DATABASE_URL" -f sql/01_schema.sql
psql "$DATABASE_URL" -f sql/02_load_from_csv.sql
psql "$DATABASE_URL" -f sql/03_views.sql
```

## Outputs
- `data/curated/` cleaned and aggregated facts
- `data/results/` forecasts, scenario results, and KPI summaries

