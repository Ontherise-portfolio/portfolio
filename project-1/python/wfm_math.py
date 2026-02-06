"""Workforce math helpers (Erlang C + staffing calculations).

Erlang C is used for real-time channels (voice/chat) to approximate ASA and SLA.
Email is treated as a throughput channel (capacity vs volume).

These functions are simplified, but great for scenario comparisons.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ErlangResult:
    traffic_erlangs: float
    agents: int
    prob_wait: float
    asa_seconds: float
    service_level: float


@dataclass(frozen=True)
class StaffingResult:
    available_agents: int
    scheduled_agents: int


def _factorial(n: int) -> float:
    # math.factorial returns int; we want float to avoid overflow patterns.
    return float(math.factorial(n))


def erlang_c_prob_wait(traffic_erlangs: float, agents: int) -> float:
    """Probability a contact waits (Erlang C).

    Returns 1.0 if unstable (traffic >= agents) or invalid.
    """
    if agents <= 0 or traffic_erlangs <= 0:
        return 1.0
    if traffic_erlangs >= agents:
        return 1.0

    a = traffic_erlangs
    n = agents

    # Sum_{k=0}^{n-1} (a^k / k!)
    s = 0.0
    for k in range(0, n):
        s += (a**k) / _factorial(k)

    # Numerator: (a^n / n!) * (n / (n - a))
    numer = (a**n) / _factorial(n) * (n / (n - a))
    denom = s + numer

    if denom <= 0:
        return 1.0
    return max(0.0, min(1.0, numer / denom))


def erlang_c_asa_seconds(traffic_erlangs: float, agents: int, aht_seconds: float) -> float:
    """Average Speed of Answer (ASA) in seconds."""
    if aht_seconds <= 0:
        return float("inf")
    if agents <= 0:
        return float("inf")
    if traffic_erlangs <= 0:
        return 0.0
    if traffic_erlangs >= agents:
        return float("inf")

    pw = erlang_c_prob_wait(traffic_erlangs, agents)
    # ASA = (Pw * AHT) / (agents - traffic)
    return (pw * aht_seconds) / max(1e-9, (agents - traffic_erlangs))


def erlang_c_service_level(
    traffic_erlangs: float,
    agents: int,
    aht_seconds: float,
    threshold_seconds: float,
) -> float:
    """Service level: P(wait <= threshold).

    SLA = 1 - Pw * exp(-(agents-traffic) * (threshold / AHT))
    """
    if threshold_seconds <= 0:
        return 0.0
    if aht_seconds <= 0:
        return 0.0
    if agents <= 0:
        return 0.0
    if traffic_erlangs <= 0:
        return 1.0
    if traffic_erlangs >= agents:
        return 0.0

    pw = erlang_c_prob_wait(traffic_erlangs, agents)
    exponent = -(agents - traffic_erlangs) * (threshold_seconds / aht_seconds)
    return max(0.0, min(1.0, 1.0 - pw * math.exp(exponent)))


def erlang_metrics(
    contacts: float,
    interval_seconds: int,
    aht_seconds: float,
    agents: int,
    sla_threshold_seconds: float,
) -> ErlangResult:
    traffic = (contacts * aht_seconds) / max(1, interval_seconds)
    pw = erlang_c_prob_wait(traffic, agents)
    asa = erlang_c_asa_seconds(traffic, agents, aht_seconds)
    sl = erlang_c_service_level(traffic, agents, aht_seconds, sla_threshold_seconds)
    return ErlangResult(traffic, agents, pw, asa, sl)


def required_agents_for_sla(
    contacts: float,
    interval_seconds: int,
    aht_seconds: float,
    sla_threshold_seconds: float,
    sla_target: float,
    max_agents: int = 500,
) -> int:
    """Smallest agent count that meets SLA target.

    Returns max_agents if target can't be met within the search range.
    """
    traffic = (contacts * aht_seconds) / max(1, interval_seconds)

    # Start at ceil(traffic) to avoid unstable solutions.
    start = max(1, int(math.ceil(traffic)))
    for n in range(start, max_agents + 1):
        sl = erlang_c_service_level(traffic, n, aht_seconds, sla_threshold_seconds)
        if sl >= sla_target:
            return n
    return max_agents


def apply_shrinkage(scheduled_agents: float, shrinkage_rate: float) -> float:
    """Convert scheduled agents to available agents."""
    r = max(0.0, min(0.95, shrinkage_rate))
    return max(0.0, scheduled_agents * (1.0 - r))

# Backwards-compatible helper names used by the generator/simulator

def erlang_c_summary(
    contacts: float,
    interval_seconds: int,
    aht_seconds: float,
    agents: int,
    sla_threshold_seconds: float,
) -> ErlangResult:
    """Return ErlangResult with traffic_erlangs, prob_wait, asa_seconds, service_level."""
    return erlang_metrics(contacts, interval_seconds, aht_seconds, agents, sla_threshold_seconds)


def required_agents_realtime(
    contacts: float,
    interval_seconds: int,
    aht_seconds: float,
    sla_threshold_seconds: float,
    sla_target: float,
    shrinkage_rate: float = 0.0,
) -> StaffingResult:
    """Return StaffingResult with available_agents and scheduled_agents for a real-time channel."""
    required_available = required_agents_for_sla(
        contacts=contacts,
        interval_seconds=interval_seconds,
        aht_seconds=aht_seconds,
        sla_threshold_seconds=sla_threshold_seconds,
        sla_target=sla_target,
    )
    # Convert available requirement to scheduled requirement.
    r = max(0.0, min(0.95, shrinkage_rate))
    required_scheduled = int(math.ceil(required_available / max(1e-9, (1.0 - r))))
    return StaffingResult(available_agents=required_available, scheduled_agents=required_scheduled)


def required_agents_throughput(
    contacts: float,
    interval_seconds: int,
    aht_seconds: float,
    shrinkage_rate: float = 0.0,
    productivity: float = 1.0,
) -> StaffingResult:
    """Return StaffingResult with available_agents and scheduled_agents for a throughput channel."""
    prod = max(0.1, productivity)
    required_available = int(math.ceil((contacts * aht_seconds) / max(1, interval_seconds) / prod))
    r = max(0.0, min(0.95, shrinkage_rate))
    required_scheduled = int(math.ceil(required_available / max(1e-9, (1.0 - r))))
    return StaffingResult(available_agents=required_available, scheduled_agents=required_scheduled)
