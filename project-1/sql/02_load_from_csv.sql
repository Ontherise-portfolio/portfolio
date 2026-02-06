-- Load curated CSVs produced by python/etl_build_marts.py
--
-- Usage example (run from repo root):
--   export DATABASE_URL=postgresql://user:pass@host:5432/db
--   psql "$DATABASE_URL" -f sql/01_schema.sql
--   psql "$DATABASE_URL" -v data_dir='data/curated/postgres_load' -f sql/02_load_from_csv.sql
--
-- NOTE: psql variables are referenced like :'data_dir'

\set ON_ERROR_STOP on

-- Clean preexisting rows (optional)
TRUNCATE TABLE wfm.fact_contacts;
TRUNCATE TABLE wfm.fact_staffing;

-- Dimensions
\copy wfm.dim_channel(channel_name,is_real_time) FROM :'data_dir'/dim_channel.csv WITH (FORMAT csv, HEADER true)
\copy wfm.dim_queue(channel_name,queue_name) FROM :'data_dir'/dim_queue.csv WITH (FORMAT csv, HEADER true)
\copy wfm.dim_time(ts_start,date,year,quarter,month,week_of_year,day_of_week,hour,minute) FROM :'data_dir'/dim_time.csv WITH (FORMAT csv, HEADER true)

-- Facts
\copy wfm.fact_contacts(ts_start,interval_minutes,channel_name,queue_name,offered_contacts,handled_contacts,abandoned_contacts,aht_seconds,asa_seconds,service_level,sla_threshold_seconds) FROM :'data_dir'/fact_contacts.csv WITH (FORMAT csv, HEADER true)
\copy wfm.fact_staffing(ts_start,interval_minutes,channel_name,queue_name,agents_scheduled,agents_available,shrinkage_rate,cost_per_hour) FROM :'data_dir'/fact_staffing.csv WITH (FORMAT csv, HEADER true)
