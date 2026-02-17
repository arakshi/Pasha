from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.models import Agent, AuditLog, Profile, Telemetry


RANGES = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def _start_for_range(range_name: str) -> datetime:
    return datetime.utcnow() - RANGES.get(range_name, timedelta(hours=24))


def _percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return float(ordered[idx])


def kpi(session: Session, range_name: str) -> dict[str, Any]:
    start = _start_for_range(range_name)
    total_agents = len(session.exec(select(Agent)).all())
    online_agents = len(session.exec(select(Agent).where(Agent.status == "online")).all())

    deployments_24h = len(
        session.exec(
            select(AuditLog).where(AuditLog.action == "APPLY_PROFILE", AuditLog.ts >= datetime.utcnow() - timedelta(hours=24))
        ).all()
    )

    telemetry = session.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    events = len(telemetry)
    error_total = sum(t.errors for t in telemetry)
    error_rate = (error_total / events * 1000) if events else 0

    one_hour_rows = session.exec(select(Telemetry).where(Telemetry.ts >= datetime.utcnow() - timedelta(hours=1))).all()
    twenty_four_rows = session.exec(select(Telemetry).where(Telemetry.ts >= datetime.utcnow() - timedelta(hours=24))).all()
    latency_1h = [x.latency_ms for x in one_hour_rows]
    latency_24h = [x.latency_ms for x in twenty_four_rows]
    avg_lat_1h = sum(latency_1h) / len(latency_1h) if latency_1h else 0
    avg_lat_24h = sum(latency_24h) / len(latency_24h) if latency_24h else 0
    p95 = _percentile(latency_24h, 0.95)

    bytes_total = sum(t.bytes_in + t.bytes_out for t in twenty_four_rows)
    traffic_gb = bytes_total / (1024 ** 3)
    availability = (online_agents / total_agents * 100) if total_agents else 0
    stability_index = max(0.0, min(100.0, 100 - error_rate * 2.2 - (p95 / 12)))

    return {
        "online_agents": online_agents,
        "total_agents": total_agents,
        "deployments_24h": deployments_24h,
        "error_rate": round(error_rate, 2),
        "avg_latency_1h": round(avg_lat_1h, 1),
        "avg_latency_24h": round(avg_lat_24h, 1),
        "p95_latency_24h": round(p95, 1),
        "traffic_24h_gb": round(traffic_gb, 2),
        "availability": round(availability, 1),
        "stability_index": round(stability_index, 1),
    }


def traffic_timeseries(session: Session, range_name: str) -> dict[str, list[Any]]:
    start = _start_for_range(range_name)
    rows = session.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"bytes_in": 0, "bytes_out": 0})
    for row in rows:
        key = row.ts.strftime("%d.%m %H:%M")
        grouped[key]["bytes_in"] += row.bytes_in
        grouped[key]["bytes_out"] += row.bytes_out
    labels = sorted(grouped.keys())
    return {
        "labels": labels,
        "bytes_in": [grouped[k]["bytes_in"] for k in labels],
        "bytes_out": [grouped[k]["bytes_out"] for k in labels],
    }


def latency_timeseries(session: Session, range_name: str) -> dict[str, list[Any]]:
    start = _start_for_range(range_name)
    rows = session.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        key = row.ts.strftime("%d.%m %H:%M")
        grouped[key].append(row.latency_ms)
    labels = sorted(grouped.keys())
    return {
        "labels": labels,
        "latency": [round(sum(grouped[k]) / len(grouped[k]), 2) for k in labels],
    }


def actions_24h(session: Session) -> dict[str, Any]:
    start = datetime.utcnow() - timedelta(hours=24)
    rows = session.exec(select(AuditLog).where(AuditLog.ts >= start)).all()
    mapped = {"PING": 0, "APPLY": 0, "STOP": 0}
    for row in rows:
        if row.action == "PING":
            mapped["PING"] += 1
        elif row.action == "APPLY_PROFILE":
            mapped["APPLY"] += 1
        elif row.action == "STOP_PROFILE":
            mapped["STOP"] += 1
    return {"labels": list(mapped.keys()), "values": list(mapped.values())}


def profile_distribution(session: Session, range_name: str) -> dict[str, Any]:
    start = _start_for_range(range_name)
    rows = session.exec(select(AuditLog).where(AuditLog.action == "APPLY_PROFILE", AuditLog.ts >= start)).all()
    profile_map = {p.id: p.name for p in session.exec(select(Profile)).all()}
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[profile_map.get(row.profile_id, "Не указан")] += 1
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top = sorted_items[:5]
    other = sum(v for _, v in sorted_items[5:])
    labels = [k for k, _ in top]
    values = [v for _, v in top]
    if other:
        labels.append("Остальные")
        values.append(other)
    return {"labels": labels, "values": values}


def top_errors_24h(session: Session) -> dict[str, Any]:
    start = datetime.utcnow() - timedelta(hours=24)
    rows = session.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    agent_map = {a.id: a.name for a in session.exec(select(Agent)).all()}
    counts: dict[int, int] = defaultdict(int)
    for row in rows:
        counts[row.agent_id] += row.errors
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:7]
    return {
        "labels": [agent_map.get(a, f"agent_{a}") for a, _ in sorted_items],
        "values": [v for _, v in sorted_items],
    }
