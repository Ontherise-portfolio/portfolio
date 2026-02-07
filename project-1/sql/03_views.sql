-- BI-friendly views

CREATE OR REPLACE VIEW wfm.vw_contacts AS
SELECT
  c.ts_start,
  c.interval_minutes,
  c.channel_name,
  c.queue_name,
  c.offered_contacts,
  c.handled_contacts,
  c.abandoned_contacts,
  c.aht_seconds,
  c.asa_seconds,
  c.service_level,
  c.sla_threshold_seconds,
  t.date_key,
  t.year,
  t.month,
  t.day,
  t.dow,
  t.hour,
  t.minute
FROM wfm.fact_contacts c
JOIN wfm.dim_time t ON t.ts_start = c.ts_start;

CREATE OR REPLACE VIEW wfm.vw_staffing AS
SELECT
  s.ts_start,
  s.interval_minutes,
  s.channel_name,
  s.queue_name,
  s.agents_scheduled,
  s.agents_available,
  s.shrinkage_rate,
  s.cost_per_hour,
  t.date_key,
  t.year,
  t.month,
  t.day,
  t.dow,
  t.hour,
  t.minute
FROM wfm.fact_staffing s
JOIN wfm.dim_time t ON t.ts_start = s.ts_start;

-- Latest forecast per grain (most recent created_at)
CREATE OR REPLACE VIEW wfm.vw_forecast_latest AS
SELECT f.*
FROM wfm.fact_forecast f
JOIN (
  SELECT ts_start, interval_minutes, channel_name, queue_name, model_name, MAX(created_at) AS max_created_at
  FROM wfm.fact_forecast
  GROUP BY 1,2,3,4,5
) x
ON f.ts_start = x.ts_start
AND f.interval_minutes = x.interval_minutes
AND f.channel_name = x.channel_name
AND f.queue_name = x.queue_name
AND f.model_name = x.model_name
AND f.created_at = x.max_created_at;

-- Scenario KPI rollups
CREATE OR REPLACE VIEW wfm.vw_scenario_kpis AS
SELECT
  sc.scenario_name,
  sim.interval_minutes,
  DATE(sim.ts_start) AS date_key,
  sim.channel_name,
  SUM(sim.required_agents) AS required_agents_sum,
  SUM(sim.scheduled_agents) AS scheduled_agents_sum,
  SUM(sim.cost_total) AS cost_total_sum,
  AVG(sim.service_level) AS service_level_avg,
  AVG(CASE WHEN sim.service_level >= (CASE WHEN sim.channel_name='voice' THEN 0.8 WHEN sim.channel_name='chat' THEN 0.75 ELSE 0.9 END) THEN 1 ELSE 0 END) AS sla_attainment_rate
FROM wfm.fact_simulation sim
JOIN wfm.dim_scenario sc ON sc.scenario_id = sim.scenario_id
GROUP BY 1,2,3,4;
