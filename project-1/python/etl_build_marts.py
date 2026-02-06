"""ETL: validate, clean, and build analytical marts.

Reads:
- demand_raw.csv
- staffing_raw.csv

Writes (parquet):
- curated/fact_contacts.parquet
- curated/fact_staffing.parquet
- curated/dim_time.parquet
- curated/dim_channel.parquet
- curated/dim_queue.parquet
- curated/aggregations/<interval>/fact_contacts.parquet
- curated/aggregations/<interval>/fact_staffing.parquet

Also writes Postgres-friendly CSVs in:
- curated/postgres_load/

"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd


AGG_INTERVAL_MINUTES = [30, 60, 480, 720, 1440]  # 30m, 1h, 8h, 12h, 24h


def _read_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing input file: {path}")
    return pd.read_csv(path)


def _validate_and_cast(demand: pd.DataFrame, staffing: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Demand
    required_demand_cols = {
        "timestamp_start",
        "interval_minutes",
        "channel",
        "queue",
        "offered_contacts",
        "handled_contacts",
        "abandoned_contacts",
        "aht_seconds",
        "asa_seconds",
        "service_level",
        "sla_threshold_seconds",
    }
    missing = required_demand_cols - set(demand.columns)
    if missing:
        raise ValueError(f"demand_raw.csv missing columns: {sorted(missing)}")

    required_staff_cols = {
        "timestamp_start",
        "interval_minutes",
        "channel",
        "queue",
        "agents_scheduled",
        "shrinkage_rate",
        "agents_available",
        "cost_per_hour",
    }
    missing = required_staff_cols - set(staffing.columns)
    if missing:
        raise ValueError(f"staffing_raw.csv missing columns: {sorted(missing)}")

    demand = demand.copy()
    staffing = staffing.copy()

    demand["timestamp_start"] = pd.to_datetime(demand["timestamp_start"], utc=True)
    staffing["timestamp_start"] = pd.to_datetime(staffing["timestamp_start"], utc=True)

    # Basic numeric coercion
    for col in ["offered_contacts", "handled_contacts", "abandoned_contacts"]:
        demand[col] = pd.to_numeric(demand[col], errors="coerce").fillna(0).astype(int)

    for col in ["aht_seconds", "asa_seconds", "service_level", "sla_threshold_seconds"]:
        demand[col] = pd.to_numeric(demand[col], errors="coerce")

    for col in ["agents_scheduled", "agents_available"]:
        staffing[col] = pd.to_numeric(staffing[col], errors="coerce").fillna(0).astype(int)

    for col in ["shrinkage_rate", "cost_per_hour"]:
        staffing[col] = pd.to_numeric(staffing[col], errors="coerce")

    demand["interval_minutes"] = pd.to_numeric(demand["interval_minutes"], errors="coerce").fillna(15).astype(int)
    staffing["interval_minutes"] = pd.to_numeric(staffing["interval_minutes"], errors="coerce").fillna(15).astype(int)

    # Normalize casing
    demand["channel"] = demand["channel"].astype(str).str.lower().str.strip()
    staffing["channel"] = staffing["channel"].astype(str).str.lower().str.strip()
    demand["queue"] = demand["queue"].astype(str).str.lower().str.strip()
    staffing["queue"] = staffing["queue"].astype(str).str.lower().str.strip()

    # Join keys
    demand = demand.sort_values(["timestamp_start", "channel", "queue"]).reset_index(drop=True)
    staffing = staffing.sort_values(["timestamp_start", "channel", "queue"]).reset_index(drop=True)

    return demand, staffing


def _build_dims(demand: pd.DataFrame, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    dim_channel = pd.DataFrame({"channel": sorted(demand["channel"].unique())})
    dim_channel["channel_id"] = np.arange(1, len(dim_channel) + 1)

    dim_queue = pd.DataFrame({"queue": sorted(demand["queue"].unique())})
    dim_queue["queue_id"] = np.arange(1, len(dim_queue) + 1)

    # Dim time from min..max timestamp in input
    tmin = demand["timestamp_start"].min()
    tmax = demand["timestamp_start"].max()
    rng = pd.date_range(tmin, tmax, freq="15min", tz="UTC")
    dim_time = pd.DataFrame({"timestamp_start": rng})
    dim_time["date"] = dim_time["timestamp_start"].dt.date
    dim_time["dow"] = dim_time["timestamp_start"].dt.dayofweek  # 0=Mon
    dim_time["hour"] = dim_time["timestamp_start"].dt.hour
    dim_time["minute"] = dim_time["timestamp_start"].dt.minute
    dim_time["week_start"] = (dim_time["timestamp_start"].dt.to_period("W").dt.start_time).dt.date

    dim_channel.to_parquet(os.path.join(out_dir, "dim_channel.parquet"), index=False)
    dim_queue.to_parquet(os.path.join(out_dir, "dim_queue.parquet"), index=False)
    dim_time.to_parquet(os.path.join(out_dir, "dim_time.parquet"), index=False)


def _aggregate_interval(
    demand: pd.DataFrame,
    staffing: pd.DataFrame,
    minutes: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate 15-min facts to a larger interval."""
    if minutes % 15 != 0:
        raise ValueError("Aggregation interval must be a multiple of 15 minutes")

    d = demand.copy()
    s = staffing.copy()

    # Floor timestamps to interval boundaries
    d["bucket"] = d["timestamp_start"].dt.floor(f"{minutes}min")
    s["bucket"] = s["timestamp_start"].dt.floor(f"{minutes}min")

    # Demand aggregation
    d_agg = (
        d.groupby(["bucket", "channel", "queue"], as_index=False)
        .agg(
            offered_contacts=("offered_contacts", "sum"),
            handled_contacts=("handled_contacts", "sum"),
            abandoned_contacts=("abandoned_contacts", "sum"),
            # Weighted AHT by handled contacts
            aht_seconds=("aht_seconds", lambda x: float(np.average(x, weights=d.loc[x.index, "handled_contacts"].clip(lower=1)))),
            # Keep SLA threshold as max (should be constant within channel)
            sla_threshold_seconds=("sla_threshold_seconds", "max"),
        )
        .rename(columns={"bucket": "timestamp_start"})
    )

    # Staffing aggregation
    # For scheduled/available agents, take average over the interval.
    s_agg = (
        s.groupby(["bucket", "channel", "queue"], as_index=False)
        .agg(
            agents_scheduled=("agents_scheduled", "mean"),
            agents_available=("agents_available", "mean"),
            shrinkage_rate=("shrinkage_rate", "mean"),
            cost_per_hour=("cost_per_hour", "mean"),
        )
        .rename(columns={"bucket": "timestamp_start"})
    )

    # Recompute ASA + service level at aggregated interval (real-time channels only)
    # We approximate using Erlang C with aggregated load.
    interval_seconds = minutes * 60
    merged = d_agg.merge(s_agg, on=["timestamp_start", "channel", "queue"], how="left")
    merged["agents_available"] = merged["agents_available"].fillna(0).round().astype(int)

    asa_list = []
    sl_list = []
    for row in merged.itertuples(index=False):
        handled = max(0, int(row.handled_contacts))
        aht = float(row.aht_seconds) if pd.notnull(row.aht_seconds) else 0.0
        agents = max(0, int(row.agents_available))
        threshold = float(row.sla_threshold_seconds) if pd.notnull(row.sla_threshold_seconds) else 0.0

        if row.channel in ("voice", "chat") and handled > 0 and agents > 0 and aht > 0:
            traffic = (handled * aht) / interval_seconds
            res = erlang_c_summary(traffic, agents, aht, threshold)
            asa_list.append(res.asa_seconds)
            sl_list.append(res.service_level)
        elif row.channel == "email" and handled > 0 and agents > 0 and aht > 0:
            capacity = agents * (interval_seconds / aht)
            sl_list.append(min(1.0, capacity / max(1.0, handled)))
            asa_list.append(float("nan"))
        else:
            asa_list.append(float("nan"))
            sl_list.append(float("nan"))

    d_agg["asa_seconds"] = asa_list
    d_agg["service_level"] = sl_list
    d_agg["interval_minutes"] = minutes
    s_agg["interval_minutes"] = minutes

    return d_agg, s_agg


def _write_postgres_load_csvs(demand: pd.DataFrame, staffing: pd.DataFrame, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    demand_out = demand.copy()
    staffing_out = staffing.copy()

    # Postgres COPY likes ISO8601 timestamps
    demand_out["timestamp_start"] = demand_out["timestamp_start"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    staffing_out["timestamp_start"] = staffing_out["timestamp_start"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    demand_out.to_csv(os.path.join(out_dir, "fact_contacts.csv"), index=False)
    staffing_out.to_csv(os.path.join(out_dir, "fact_staffing.csv"), index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in_dir", required=True, help="Directory containing demand_raw.csv and staffing_raw.csv")
    parser.add_argument("--out_dir", required=True, help="Output directory (curated)")
    args = parser.parse_args()

    in_dir = args.in_dir
    out_dir = args.out_dir

    os.makedirs(out_dir, exist_ok=True)

    demand = _read_csv(os.path.join(in_dir, "demand_raw.csv"))
    staffing = _read_csv(os.path.join(in_dir, "staffing_raw.csv"))

    demand, staffing = _validate_and_cast(demand, staffing)

    # Base 15m facts
    demand.to_parquet(os.path.join(out_dir, "fact_contacts.parquet"), index=False)
    staffing.to_parquet(os.path.join(out_dir, "fact_staffing.parquet"), index=False)

    # Dims
    _build_dims(demand, out_dir)

    # Aggregations
    agg_root = os.path.join(out_dir, "aggregations")
    for minutes in AGG_INTERVAL_MINUTES:
        d_agg, s_agg = _aggregate_interval(demand, staffing, minutes)
        d_path = os.path.join(agg_root, f"{minutes}m")
        os.makedirs(d_path, exist_ok=True)
        d_agg.to_parquet(os.path.join(d_path, "fact_contacts.parquet"), index=False)
        s_agg.to_parquet(os.path.join(d_path, "fact_staffing.parquet"), index=False)

    # Postgres load CSVs (15m base)
    _write_postgres_load_csvs(demand, staffing, os.path.join(out_dir, "postgres_load"))

    print(f"Wrote curated marts to: {out_dir}")


if __name__ == "__main__":
    # Avoid expensive import-time work; main is fast.
    from wfm_math import erlang_c_summary

    main()
