"""Generate synthetic call-center demand and staffing data.

Outputs (CSV):
- demand_raw.csv: interval-level demand by channel/queue
- staffing_raw.csv: interval-level scheduled/available agents by channel/queue

Base interval is 15 minutes.
Aggregations to 30m/1h/8h/12h/24h are handled in the ETL step.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from wfm_math import required_agents_realtime, required_agents_throughput, erlang_c_summary


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    queues: list[str]
    sla_threshold_seconds: int
    base_rate_per_15m: dict[str, float]  # per queue
    cost_per_hour: float
    aht_mean_seconds: dict[str, float]


def _hour_curve(hour: int) -> float:
    # Business-hours peak with morning and afternoon bumps.
    if 0 <= hour < 6:
        return 0.15
    if 6 <= hour < 9:
        return 0.7
    if 9 <= hour < 12:
        return 1.15
    if 12 <= hour < 14:
        return 1.0
    if 14 <= hour < 17:
        return 1.2
    if 17 <= hour < 20:
        return 0.85
    return 0.35


def _dow_curve(dow: int) -> float:
    # dow: Monday=0 ... Sunday=6
    if dow in (5, 6):
        return 0.55
    if dow == 0:
        return 1.1
    if dow == 4:
        return 0.95
    return 1.0


def _holiday_shock(date: datetime, rng: np.random.Generator) -> float:
    # Occasionally create a one-day surge or dip.
    # (Keeps the dataset interesting for scenario testing.)
    if rng.random() < 0.015:
        return rng.uniform(1.25, 1.65)
    if rng.random() < 0.01:
        return rng.uniform(0.6, 0.85)
    return 1.0


def build_configs() -> list[ChannelConfig]:
    return [
        ChannelConfig(
            name="voice",
            queues=["billing", "tech", "sales"],
            sla_threshold_seconds=20,
            base_rate_per_15m={"billing": 18.0, "tech": 14.0, "sales": 9.0},
            cost_per_hour=24.0,
            aht_mean_seconds={"billing": 420.0, "tech": 540.0, "sales": 480.0},
        ),
        ChannelConfig(
            name="chat",
            queues=["web_support", "sales_chat"],
            sla_threshold_seconds=30,
            base_rate_per_15m={"web_support": 11.0, "sales_chat": 7.0},
            cost_per_hour=22.0,
            aht_mean_seconds={"web_support": 360.0, "sales_chat": 330.0},
        ),
        ChannelConfig(
            name="email",
            queues=["support_email", "billing_email"],
            sla_threshold_seconds=24 * 3600,
            base_rate_per_15m={"support_email": 5.5, "billing_email": 4.5},
            cost_per_hour=21.0,
            aht_mean_seconds={"support_email": 720.0, "billing_email": 600.0},
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    start_dt = datetime.strptime(args.start, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=args.days)

    rng = np.random.default_rng(args.seed)
    interval_minutes = 15
    interval_seconds = interval_minutes * 60

    configs = build_configs()

    rows_demand: list[dict] = []
    rows_staffing: list[dict] = []

    # Build a day-level shock map so it stays consistent across intervals.
    day_shock: dict[str, float] = {}
    d = start_dt
    while d < end_dt:
        day_shock[d.strftime("%Y-%m-%d")] = _holiday_shock(d, rng)
        d += timedelta(days=1)

    ts = start_dt
    while ts < end_dt:
        hour = ts.hour
        dow = ts.weekday()
        curve = _hour_curve(hour) * _dow_curve(dow) * day_shock[ts.strftime("%Y-%m-%d")]

        # A gentle long-term trend (useful for forecast evaluation).
        days_from_start = (ts - start_dt).days
        trend = 1.0 + 0.0008 * days_from_start

        # Shared noise component for correlated fluctuations.
        shared_noise = rng.normal(1.0, 0.05)

        for cfg in configs:
            for q in cfg.queues:
                base = cfg.base_rate_per_15m[q]

                # Channel-specific shaping
                if cfg.name == "email":
                    # Email tends to cluster during business hours.
                    ch_mult = 1.1 if 8 <= hour <= 17 else 0.4
                elif cfg.name == "chat":
                    ch_mult = 1.15 if 10 <= hour <= 18 else 0.55
                else:  # voice
                    ch_mult = 1.0

                lam = max(0.1, base * curve * trend * shared_noise * ch_mult)
                offered = int(rng.poisson(lam))

                # AHT varies a bit interval to interval.
                aht = max(60.0, rng.lognormal(mean=math.log(cfg.aht_mean_seconds[q]), sigma=0.12))

                # Abandonments for real-time channels.
                if cfg.name in ("voice", "chat"):
                    base_abandon = 0.03 if cfg.name == "voice" else 0.04
                    p_abandon = min(0.22, max(0.0, rng.normal(base_abandon, 0.01)))
                    abandoned = int(rng.binomial(offered, p_abandon)) if offered > 0 else 0
                else:
                    abandoned = 0

                handled = max(0, offered - abandoned)

                # Staffing plan: compute "needed" then add small planning errors.
                if cfg.name in ("voice", "chat"):
                    shrinkage = float(np.clip(rng.normal(0.28, 0.03), 0.15, 0.45))
                    staffing_req = required_agents_realtime(
                        contacts=handled,
                        aht_seconds=float(aht),
                        interval_seconds=interval_seconds,
                        sla_threshold_seconds=cfg.sla_threshold_seconds,
                        sla_target=0.8 if cfg.name == "voice" else 0.75,
                        shrinkage_rate=shrinkage,
                    )
                    needed = staffing_req.scheduled_agents
                else:
                    shrinkage = float(np.clip(rng.normal(0.25, 0.03), 0.10, 0.40))
                    staffing_req = required_agents_throughput(
                        contacts=handled,
                        aht_seconds=float(aht),
                        interval_seconds=interval_seconds,
                        shrinkage_rate=shrinkage,
                        productivity=0.82,
                    )
                    needed = staffing_req.scheduled_agents

                # Planning error and schedule rounding.
                schedule_bias = rng.normal(1.0, 0.06)
                scheduled = int(max(0, round(needed * schedule_bias)))
                available = int(max(0, math.floor(scheduled * (1.0 - shrinkage))))

                # Service metrics based on available (actual).
                if cfg.name in ("voice", "chat"):
                    summary = erlang_c_summary(
                        contacts=handled,
                        aht_seconds=float(aht),
                        interval_seconds=interval_seconds,
                        agents=available,
                        sla_threshold_seconds=cfg.sla_threshold_seconds,
                    )
                    asa = summary.asa_seconds
                    sl = summary.service_level
                else:
                    # Throughput: capacity-based.
                    capacity = (available * interval_seconds) / max(1e-6, float(aht))
                    sl = 1.0 if handled == 0 else float(min(1.0, capacity / handled))
                    asa = 0.0

                rows_demand.append(
                    {
                        "timestamp_start": ts.isoformat(sep=" "),
                        "interval_minutes": interval_minutes,
                        "channel": cfg.name,
                        "queue": q,
                        "offered_contacts": offered,
                        "handled_contacts": handled,
                        "abandoned_contacts": abandoned,
                        "aht_seconds": round(float(aht), 2),
                        "asa_seconds": round(float(asa), 2) if math.isfinite(asa) else None,
                        "sla_threshold_seconds": cfg.sla_threshold_seconds,
                        "service_level": round(float(sl), 4),
                    }
                )

                rows_staffing.append(
                    {
                        "timestamp_start": ts.isoformat(sep=" "),
                        "interval_minutes": interval_minutes,
                        "channel": cfg.name,
                        "queue": q,
                        "agents_scheduled": scheduled,
                        "shrinkage_rate": round(float(shrinkage), 4),
                        "agents_available": available,
                        "cost_per_hour": cfg.cost_per_hour,
                    }
                )

        ts += timedelta(minutes=interval_minutes)

    demand_df = pd.DataFrame(rows_demand)
    staffing_df = pd.DataFrame(rows_staffing)

    demand_path = os.path.join(args.out_dir, "demand_raw.csv")
    staffing_path = os.path.join(args.out_dir, "staffing_raw.csv")

    demand_df.to_csv(demand_path, index=False)
    staffing_df.to_csv(staffing_path, index=False)

    print(f"Wrote {len(demand_df):,} rows -> {demand_path}")
    print(f"Wrote {len(staffing_df):,} rows -> {staffing_path}")


if __name__ == "__main__":
    import math

    main()
