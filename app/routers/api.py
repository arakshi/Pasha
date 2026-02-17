from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.database import engine
from app.models import Telemetry
from app.services import metrics

router = APIRouter()


@router.get("/api/metrics/kpi")
def get_kpi(range: str = Query("24h")):
    with Session(engine) as session:
        return metrics.kpi(session, range)


@router.get("/api/metrics/traffic")
def get_traffic(range: str = Query("1h")):
    with Session(engine) as session:
        return metrics.traffic_timeseries(session, range)


@router.get("/api/metrics/latency")
def get_latency(range: str = Query("1h")):
    with Session(engine) as session:
        return metrics.latency_timeseries(session, range)


@router.get("/api/metrics/actions")
def get_actions(range: str = Query("24h")):
    _ = range
    with Session(engine) as session:
        return metrics.actions_24h(session)


@router.get("/api/metrics/profile_distribution")
def get_profile_distribution(range: str = Query("7d")):
    with Session(engine) as session:
        return metrics.profile_distribution(session, range)


@router.get("/api/metrics/top_errors")
def get_top_errors(range: str = Query("24h")):
    _ = range
    with Session(engine) as session:
        return metrics.top_errors_24h(session)


@router.get("/api/telemetry/export.csv")
def export_telemetry(range: str = Query("24h")):
    now = datetime.utcnow()
    if range == "24h":
        start = now - timedelta(hours=24)
    elif range == "1h":
        start = now - timedelta(hours=1)
    else:
        start = now - timedelta(days=7)

    with Session(engine) as session:
        rows = session.exec(select(Telemetry).where(Telemetry.ts >= start).order_by(Telemetry.ts.desc())).all()

    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["id", "ts", "agent_id", "bytes_in", "bytes_out", "latency_ms", "errors", "profile_id", "scenario"])
    for r in rows:
        writer.writerow([r.id, r.ts.isoformat(), r.agent_id, r.bytes_in, r.bytes_out, r.latency_ms, r.errors, r.profile_id, r.scenario])
    stream.seek(0)

    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=telemetry_export.csv"},
    )
