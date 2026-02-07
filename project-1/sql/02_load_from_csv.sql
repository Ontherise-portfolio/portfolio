-- Load curated CSVs produced by python/etl_build_marts.py
--
-- Run from the project-1 directory:
--   psql -U postgres -d wfm -f sql/02_load_from_csv.sql

\set ON_ERROR_STOP on

-- Clean preexisting rows (optional)
TRUNCATE TABLE wfm.fact_contacts;
TRUNCATE TABLE wfm.fact_staffing;

-- Dimensions
\copy wfm.dim_channel(channel_name,is_real_time) FROM 'data/curated/postgres_load/dim_channel.csv' WITH (FORMAT csv, HEADER true)
\copy wfm.dim_queue(channel_name,queue_name) FROM 'data/curated/postgres_load/dim_queue.csv' WITH (FORMAT csv, HEADER true)
\copy wfm.dim_time(ts_start,date_key,year,month,day,dow,hour,minute) FROM 'data/curated/postgres_load/dim_time.csv' WITH (FORMAT csv, HEADER true)

-- Facts
\copy wfm.fact_contacts(ts_start,interval_minutes,channel_name,queue_name,offered_contacts,handled_contacts,abandoned_contacts,aht_seconds,asa_seconds,service_level,sla_threshold_seconds) FROM 'data/curated/postgres_load/fact_contacts.csv' WITH (FORMAT csv, HEADER true)
\copy wfm.fact_staffing(ts_start,interval_minutes,channel_name,queue_name,agents_scheduled,agents_available,shrinkage_rate,cost_per_hour) FROM 'data/curated/postgres_load/fact_staffing.csv' WITH (FORMAT csv, HEADER true)
