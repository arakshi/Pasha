from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.models import Agent, AuditLog, Telemetry


RANGES = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def _start_for_range(range_name: str) -> datetime:
    return datetime.utcnow() - RANGES.get(range_name, timedelta(hours=24))


def kpi(session: Session, range_name: str) -> dict[str, Any]:
    start = _start_for_range(range_name)
    total_agents = len(session.exec(select(Agent)).all())
    online_agents = len(session.exec(select(Agent).where(Agent.status == "online")).all())
    deploy_24h = len(
        session.exec(
            select(AuditLog).where(AuditLog.action == "APPLY_PROFILE", AuditLog.ts >= datetime.utcnow() - timedelta(hours=24))
        ).all()
    )

    telemetry = session.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    event_count = len(telemetry)
    error_total = sum(t.errors for t in telemetry)
    error_rate = (error_total / event_count * 1000) if event_count else 0

    t1h = session.exec(select(Telemetry).where(Telemetry.ts >= datetime.utcnow() - timedelta(hours=1))).all()
    avg_lat_1h = sum(x.latency_ms for x in t1h) / len(t1h) if t1h else 0
    t24 = session.exec(select(Telemetry).where(Telemetry.ts >= datetime.utcnow() - timedelta(hours=24))).all()
    avg_lat_24h = sum(x.latency_ms for x in t24) / len(t24) if t24 else 0

    return {
        "online_agents": online_agents,
        "total_agents": total_agents,
        "deployments_24h": deploy_24h,
        "error_rate": round(error_rate, 2),
        "avg_latency_1h": round(avg_lat_1h, 1),
        "avg_latency_24h": round(avg_lat_24h, 1),
    }


def traffic_timeseries(session: Session, range_name: str) -> dict[str, list[Any]]:
    start = _start_for_range(range_name)
    rows = session.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"bytes_in": 0, "bytes_out": 0})
    for row in rows:
        key = row.ts.strftime("%Y-%m-%d %H:%M")
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
        key = row.ts.strftime("%Y-%m-%d %H:%M")
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
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.profile_id)] += 1
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top = sorted_items[:5]
    other = sum(v for _, v in sorted_items[5:])
    labels = [f"profile_{k}" for k, _ in top]
    values = [v for _, v in top]
    if other:
        labels.append("other")
        values.append(other)
    return {"labels": labels, "values": values}


def top_errors_24h(session: Session) -> dict[str, Any]:
    start = datetime.utcnow() - timedelta(hours=24)
    rows = session.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    counts: dict[int, int] = defaultdict(int)
    for row in rows:
        counts[row.agent_id] += row.errors
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "labels": [f"agent_{a}" for a, _ in sorted_items],
        "values": [v for _, v in sorted_items],
    }
