"""Forecast demand and simulate staffing scenarios.

Inputs (from ETL step):
- curated/aggregations/<interval>m/fact_contacts.parquet
- curated/aggregations/<interval>m/fact_staffing.parquet

Outputs:
- forecasts/forecast_<interval>m.parquet
- results/scenario_results_<interval>m.parquet
- results/kpi_summary_<interval>m.csv
- results/model_quality_<interval>m.csv

Forecast model (fast & robust for portfolio use):
- Builds a seasonal profile by (day_of_week, time_bucket)
- Estimates a low-order trend on daily totals
- Forecast = profile * trend

Scenarios include demand shifts, shrinkage changes, and wage changes.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from wfm_math import (
    erlang_c_summary,
    required_agents_realtime,
    required_agents_throughput,
)


ALLOWED_INTERVAL_MINUTES = [15, 30, 60, 480, 720, 1440]


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    name: str
    demand_multiplier: float
    shrinkage_delta: float  # absolute change (e.g., +0.03 = +3pp)
    wage_multiplier: float
    staffing_buffer: float  # fraction, e.g., 0.10 = schedule 10% above required


DEFAULT_SCENARIOS = [
    Scenario("base", "Baseline", 1.00, 0.00, 1.00, 0.08),
    Scenario("hi_demand", "High demand (+10%)", 1.10, 0.00, 1.00, 0.08),
    Scenario("lo_demand", "Low demand (-10%)", 0.90, 0.00, 1.00, 0.08),
    Scenario("hi_shrink", "Shrinkage up (+5pp)", 1.00, 0.05, 1.00, 0.08),
    Scenario("lo_shrink", "Shrinkage down (-5pp)", 1.00, -0.05, 1.00, 0.08),
    Scenario("wage_up", "Wage up (+10%)", 1.00, 0.00, 1.10, 0.08),
    Scenario("aggressive", "Aggressive service (buffer 20%)", 1.00, 0.00, 1.00, 0.20),
]


def _load_inputs(in_dir: str, interval_minutes: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = os.path.join(in_dir, "aggregations", f"{interval_minutes}m")
    contacts = pd.read_parquet(os.path.join(path, "fact_contacts.parquet"))
    staffing = pd.read_parquet(os.path.join(path, "fact_staffing.parquet"))

    for df in (contacts, staffing):
        df["interval_start"] = pd.to_datetime(df["interval_start"], utc=False)

    return contacts, staffing


def _time_bucket(ts: pd.Series, interval_minutes: int) -> pd.Series:
    # Bucket within a day: 0..(day_minutes/interval_minutes - 1)
    minutes_from_midnight = ts.dt.hour * 60 + ts.dt.minute
    return (minutes_from_midnight // interval_minutes).astype(int)


def _fit_profile_and_trend(series_df: pd.DataFrame, interval_minutes: int) -> dict:
    """Fit seasonal profile and daily trend for one channel/queue series."""
    df = series_df.copy()
    df["dow"] = df["interval_start"].dt.dayofweek
    df["bucket"] = _time_bucket(df["interval_start"], interval_minutes)

    # Use robust median profile to reduce sensitivity to synthetic spikes.
    profile = (
        df.groupby(["dow", "bucket"])["offered_contacts"]
        .median()
        .rename("profile")
        .reset_index()
    )

    # Daily totals for trend.
    daily = df.resample("D", on="interval_start")["offered_contacts"].sum().reset_index()
    daily["t"] = np.arange(len(daily), dtype=float)

    # Simple linear trend fit (clipped to avoid negative).
    if len(daily) >= 7:
        x = daily["t"].values
        y = daily["offered_contacts"].values
        x_mean = x.mean()
        y_mean = y.mean()
        denom = ((x - x_mean) ** 2).sum()
        slope = 0.0 if denom == 0 else (((x - x_mean) * (y - y_mean)).sum() / denom)
        intercept = y_mean - slope * x_mean
    else:
        slope = 0.0
        intercept = float(daily["offered_contacts"].mean()) if len(daily) else 0.0

    # Baseline day-0 value for scaling.
    base_level = max(1e-6, float(daily["offered_contacts"].tail(28).mean())) if len(daily) else 1.0

    return {
        "profile": profile,
        "trend_slope": slope,
        "trend_intercept": intercept,
        "base_level": base_level,
    }


def _forecast_series(model: dict, future_index: pd.DatetimeIndex, interval_minutes: int) -> pd.Series:
    # Build the seasonal profile lookup.
    prof = model["profile"].copy()
    prof["key"] = prof["dow"].astype(str) + "_" + prof["bucket"].astype(str)
    prof_map = dict(zip(prof["key"], prof["profile"].astype(float)))

    future_df = pd.DataFrame({"interval_start": future_index})
    future_df["dow"] = future_df["interval_start"].dt.dayofweek
    future_df["bucket"] = _time_bucket(future_df["interval_start"], interval_minutes)
    future_df["key"] = future_df["dow"].astype(str) + "_" + future_df["bucket"].astype(str)

    # Trend scales daily totals; convert to per-interval scaling.
    future_df["day"] = future_df["interval_start"].dt.floor("D")
    day_ord = (future_df["day"].rank(method="dense").astype(int) - 1).astype(float)
    daily_total = model["trend_intercept"] + model["trend_slope"] * day_ord
    daily_total = np.maximum(0.0, daily_total)

    # Profile sum per day for normalization.
    # Compute expected total from profile for each dow.
    prof_totals = model["profile"].groupby("dow")["profile"].sum().to_dict()
    expected_total = future_df["dow"].map(lambda d: max(1e-6, float(prof_totals.get(int(d), 1.0))))

    base = future_df["key"].map(lambda k: float(prof_map.get(k, 0.0)))
    forecast = base * (daily_total / expected_total)

    return forecast.astype(float)


def _evaluate_forecast(actual: pd.Series, pred: pd.Series) -> dict:
    # Avoid divide-by-zero in MAPE.
    eps = 1e-6
    a = actual.astype(float).values
    p = pred.astype(float).values
    mape = float(np.mean(np.abs(a - p) / np.maximum(eps, np.abs(a))))
    rmse = float(np.sqrt(np.mean((a - p) ** 2)))
    return {"mape": mape, "rmse": rmse}


def _simulate_scenario(
    forecast_df: pd.DataFrame,
    staffing_ref: pd.DataFrame,
    interval_minutes: int,
    scenario: Scenario,
) -> pd.DataFrame:
    df = forecast_df.copy()

    # Merge staffing reference to get costs, shrinkage, and SLA thresholds.
    staff_cols = [
        "channel",
        "queue",
        "cost_per_hour",
        "shrinkage_rate",
        "sla_threshold_seconds",
        "aht_seconds",
        "is_realtime",
    ]
    ref = staffing_ref[staff_cols].drop_duplicates(subset=["channel", "queue"])
    df = df.merge(ref, on=["channel", "queue"], how="left")

    df["scenario_id"] = scenario.scenario_id
    df["scenario_name"] = scenario.name

    df["forecast_offered"] = df["forecast_offered"] * scenario.demand_multiplier

    shrink = np.clip(df["shrinkage_rate"].fillna(0.30) + scenario.shrinkage_delta, 0.0, 0.70)
    df["scenario_shrinkage"] = shrink

    df["scenario_cost_per_hour"] = df["cost_per_hour"].fillna(22.0) * scenario.wage_multiplier

    interval_seconds = interval_minutes * 60
    interval_hours = interval_minutes / 60.0

    # Required agents
    req_agents = []
    achieved_sla = []
    achieved_asa = []

    for row in df.itertuples(index=False):
        offered = max(0.0, float(row.forecast_offered))
        aht = max(1.0, float(row.aht_seconds))
        thr = max(1.0, float(row.sla_threshold_seconds))
        is_rt = bool(row.is_realtime)
        shrinkage = max(0.0, float(row.scenario_shrinkage))

        if is_rt:
            req = required_agents_realtime(
                contacts=offered,
                aht_seconds=aht,
                interval_seconds=interval_seconds,
                sla_threshold_seconds=thr,
                sla_target=0.80,
                shrinkage=shrinkage,
                occupancy_cap=0.85,
            )
            er = erlang_c_summary(
                contacts=offered,
                aht_seconds=aht,
                interval_seconds=interval_seconds,
                agents_available=int(req.available_agents),
                sla_threshold_seconds=thr,
            )
            req_agents.append(req.scheduled_agents)
            achieved_sla.append(er.service_level)
            achieved_asa.append(er.asa_seconds)
        else:
            req = required_agents_throughput(
                contacts=offered,
                aht_seconds=aht,
                interval_seconds=interval_seconds,
                shrinkage=shrinkage,
                buffer=scenario.staffing_buffer,
            )
            # Throughput SLA proxy: capacity / demand
            capacity_contacts = (req.available_agents * interval_seconds) / aht
            sla = 1.0 if offered <= 0 else float(min(1.0, capacity_contacts / offered))
            req_agents.append(req.scheduled_agents)
            achieved_sla.append(sla)
            achieved_asa.append(float("nan"))

    df["required_agents_scheduled"] = req_agents

    # Planned schedule = required + scenario buffer
    planned = np.ceil(df["required_agents_scheduled"] * (1.0 + scenario.staffing_buffer)).astype(int)
    df["planned_agents_scheduled"] = planned
    df["planned_agents_available"] = np.floor(planned * (1.0 - df["scenario_shrinkage"])).astype(int)

    # Service/cost with planned schedule
    costs = df["planned_agents_scheduled"] * df["scenario_cost_per_hour"] * interval_hours
    df["planned_labor_cost"] = costs

    # Recompute achieved SLA using planned availability (for real-time)
    new_sla = []
    new_asa = []
    for row, avail in zip(df.itertuples(index=False), df["planned_agents_available"].values):
        offered = max(0.0, float(row.forecast_offered))
        aht = max(1.0, float(row.aht_seconds))
        thr = max(1.0, float(row.sla_threshold_seconds))
        is_rt = bool(row.is_realtime)

        if is_rt:
            er = erlang_c_summary(
                contacts=offered,
                aht_seconds=aht,
                interval_seconds=interval_seconds,
                agents_available=int(avail),
                sla_threshold_seconds=thr,
            )
            new_sla.append(er.service_level)
            new_asa.append(er.asa_seconds)
        else:
            capacity_contacts = (int(avail) * interval_seconds) / aht
            sla = 1.0 if offered <= 0 else float(min(1.0, capacity_contacts / offered))
            new_sla.append(sla)
            new_asa.append(float("nan"))

    df["achieved_service_level"] = new_sla
    df["achieved_asa_seconds"] = new_asa

    df["under_over_staffed"] = df["planned_agents_scheduled"] - df["required_agents_scheduled"]

    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in_dir", required=True, help="Curated output dir from ETL")
    ap.add_argument("--out_dir", required=True, help="Where to write forecasts/results")
    ap.add_argument("--interval_minutes", type=int, default=60, choices=ALLOWED_INTERVAL_MINUTES)
    ap.add_argument("--horizon_days", type=int, default=28)
    ap.add_argument("--holdout_days", type=int, default=14)
    args = ap.parse_args()

    contacts, staffing = _load_inputs(args.in_dir, args.interval_minutes)

    # Identify per series metadata from staffing facts (costs, shrinkage, AHT, SLA thresholds)
    meta = (
        staffing.groupby(["channel", "queue"])
        .agg(
            cost_per_hour=("cost_per_hour", "mean"),
            shrinkage_rate=("shrinkage_rate", "mean"),
            aht_seconds=("aht_seconds", "mean"),
            sla_threshold_seconds=("sla_threshold_seconds", "max"),
            is_realtime=("is_realtime", "max"),
        )
        .reset_index()
    )

    # Build forecasts for each channel/queue
    forecasts = []
    quality_rows = []

    for (channel, queue), df_series in contacts.groupby(["channel", "queue"], sort=False):
        df_series = df_series.sort_values("interval_start")

        # Holdout split
        cutoff = df_series["interval_start"].max() - pd.Timedelta(days=args.holdout_days)
        train = df_series[df_series["interval_start"] <= cutoff]
        test = df_series[df_series["interval_start"] > cutoff]

        model = _fit_profile_and_trend(train, args.interval_minutes)

        # Evaluate on holdout
        if len(test) > 0:
            pred_test = _forecast_series(model, pd.DatetimeIndex(test["interval_start"]), args.interval_minutes)
            q = _evaluate_forecast(test["offered_contacts"], pred_test)
            quality_rows.append(
                {
                    "channel": channel,
                    "queue": queue,
                    "mape": q["mape"],
                    "rmse": q["rmse"],
                    "holdout_days": args.holdout_days,
                }
            )

        # Forecast future
        last_ts = df_series["interval_start"].max()
        freq = f"{args.interval_minutes}min"
        future_index = pd.date_range(
            start=last_ts + pd.Timedelta(minutes=args.interval_minutes),
            periods=int(args.horizon_days * 24 * 60 / args.interval_minutes),
            freq=freq,
        )
        pred_future = _forecast_series(model, future_index, args.interval_minutes)

        f = pd.DataFrame(
            {
                "interval_start": future_index,
                "channel": channel,
                "queue": queue,
                "forecast_offered": pred_future.values,
                "interval_minutes": args.interval_minutes,
            }
        )
        forecasts.append(f)

    forecast_df = pd.concat(forecasts, ignore_index=True)

    # Write forecast parquet
    os.makedirs(args.out_dir, exist_ok=True)
    forecast_path = os.path.join(args.out_dir, f"forecast_{args.interval_minutes}m.parquet")
    forecast_df.to_parquet(forecast_path, index=False)

    # Run scenarios
    scenario_frames = []
    for sc in DEFAULT_SCENARIOS:
        scenario_frames.append(_simulate_scenario(forecast_df, meta, args.interval_minutes, sc))

    scenario_df = pd.concat(scenario_frames, ignore_index=True)
    scenario_path = os.path.join(args.out_dir, f"scenario_results_{args.interval_minutes}m.parquet")
    scenario_df.to_parquet(scenario_path, index=False)

    # KPI summary
    scenario_df["date"] = scenario_df["interval_start"].dt.date
    kpi = (
        scenario_df.groupby(["scenario_id", "scenario_name", "date", "channel"], sort=False)
        .agg(
            forecast_offered=("forecast_offered", "sum"),
            planned_labor_cost=("planned_labor_cost", "sum"),
            avg_service_level=("achieved_service_level", "mean"),
            avg_asa_seconds=("achieved_asa_seconds", "mean"),
            avg_under_over=("under_over_staffed", "mean"),
        )
        .reset_index()
    )
    kpi.to_csv(os.path.join(args.out_dir, f"kpi_summary_{args.interval_minutes}m.csv"), index=False)

    # Model quality
    quality = pd.DataFrame(quality_rows)
    if len(quality) == 0:
        quality = pd.DataFrame(columns=["channel", "queue", "mape", "rmse", "holdout_days"])
    quality.to_csv(os.path.join(args.out_dir, f"model_quality_{args.interval_minutes}m.csv"), index=False)

    print(f"Wrote forecast: {forecast_path}")
    print(f"Wrote scenario results: {scenario_path}")


if __name__ == "__main__":
    main()
