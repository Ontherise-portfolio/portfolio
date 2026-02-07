-- Project 1: Workforce Demand & Staffing Forecast Simulator
-- PostgreSQL schema

CREATE SCHEMA IF NOT EXISTS wfm;

-- Dimensions
CREATE TABLE IF NOT EXISTS wfm.dim_channel (
  channel_id SMALLSERIAL PRIMARY KEY,
  channel_name TEXT NOT NULL UNIQUE,
  is_real_time BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS wfm.dim_queue (
  queue_id SMALLSERIAL PRIMARY KEY,
  channel_name TEXT NOT NULL,
  queue_name TEXT NOT NULL,
  UNIQUE(channel_name, queue_name)
);

CREATE TABLE IF NOT EXISTS wfm.dim_time (
  time_id BIGSERIAL PRIMARY KEY,
  ts_start TIMESTAMP NOT NULL UNIQUE,
  date_key DATE NOT NULL,
  year SMALLINT NOT NULL,
  month SMALLINT NOT NULL,
  day SMALLINT NOT NULL,
  dow SMALLINT NOT NULL,
  hour SMALLINT NOT NULL,
  minute SMALLINT NOT NULL
);

-- Facts (base interval or aggregated)
CREATE TABLE IF NOT EXISTS wfm.fact_contacts (
  ts_start TIMESTAMP NOT NULL,
  interval_minutes SMALLINT NOT NULL,
  channel_name TEXT NOT NULL,
  queue_name TEXT NOT NULL,
  offered_contacts INTEGER NOT NULL,
  handled_contacts INTEGER NOT NULL,
  abandoned_contacts INTEGER NOT NULL,
  aht_seconds DOUBLE PRECISION NOT NULL,
  asa_seconds DOUBLE PRECISION,
  service_level DOUBLE PRECISION,
  sla_threshold_seconds INTEGER,
  PRIMARY KEY (ts_start, interval_minutes, channel_name, queue_name)
);

CREATE TABLE IF NOT EXISTS wfm.fact_staffing (
  ts_start TIMESTAMP NOT NULL,
  interval_minutes SMALLINT NOT NULL,
  channel_name TEXT NOT NULL,
  queue_name TEXT NOT NULL,
  agents_scheduled INTEGER NOT NULL,
  agents_available INTEGER NOT NULL,
  shrinkage_rate DOUBLE PRECISION NOT NULL,
  cost_per_hour DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (ts_start, interval_minutes, channel_name, queue_name)
);

-- Forecasts
CREATE TABLE IF NOT EXISTS wfm.fact_forecast (
  ts_start TIMESTAMP NOT NULL,
  interval_minutes SMALLINT NOT NULL,
  channel_name TEXT NOT NULL,
  queue_name TEXT NOT NULL,
  model_name TEXT NOT NULL,
  forecast_offered DOUBLE PRECISION NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (ts_start, interval_minutes, channel_name, queue_name, model_name, created_at)
);

-- Scenarios
CREATE TABLE IF NOT EXISTS wfm.dim_scenario (
  scenario_id SMALLSERIAL PRIMARY KEY,
  scenario_name TEXT NOT NULL UNIQUE,
  demand_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  shrinkage_delta DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  wage_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  staffing_buffer_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS wfm.fact_simulation (
  scenario_id SMALLINT NOT NULL REFERENCES wfm.dim_scenario(scenario_id),
  ts_start TIMESTAMP NOT NULL,
  interval_minutes SMALLINT NOT NULL,
  channel_name TEXT NOT NULL,
  queue_name TEXT NOT NULL,
  required_agents INTEGER NOT NULL,
  scheduled_agents INTEGER NOT NULL,
  service_level DOUBLE PRECISION,
  cost_total DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (scenario_id, ts_start, interval_minutes, channel_name, queue_name)
);

CREATE INDEX IF NOT EXISTS idx_fact_contacts_date ON wfm.fact_contacts (ts_start);
CREATE INDEX IF NOT EXISTS idx_fact_staffing_date ON wfm.fact_staffing (ts_start);
CREATE INDEX IF NOT EXISTS idx_fact_sim_scenario ON wfm.fact_simulation (scenario_id, ts_start);
