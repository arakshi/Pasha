from __future__ import annotations

from datetime import datetime
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import engine
from app.models import Agent, AuditLog, Profile, Telemetry, TestRun, User
from app.services.agent_sim import apply_profile, stop_profile
from app.services.metrics import kpi

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def current_user(username: str | None) -> User:
    name = username or "admin"
    with Session(engine) as session:
        found = session.exec(select(User).where(User.username == name)).first()
        if found:
            return found
        return session.exec(select(User)).first()


@router.get("/", response_class=HTMLResponse)
def root(request: Request):
    return RedirectResponse("/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: str | None = None):
    cu = current_user(user)
    with Session(engine) as session:
        summary = kpi(session, "24h")
        trend = session.exec(select(Telemetry).order_by(Telemetry.ts.desc()).limit(30)).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"user": cu, "summary": summary, "trend_json": json.dumps([{"ts": t.ts.strftime('%H:%M'), "in": t.bytes_in, "out": t.bytes_out} for t in reversed(trend)])},
    )


@router.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request, search: str = "", status: str = "all", sort: str = "desc", user: str | None = None):
    cu = current_user(user)
    with Session(engine) as session:
        query = select(Agent)
        if search:
            query = query.where(Agent.name.contains(search))
        if status in {"online", "offline"}:
            query = query.where(Agent.status == status)
        order_clause = Agent.last_seen.desc() if sort == "desc" else Agent.last_seen.asc()
        agents = session.exec(query.order_by(order_clause)).all()

        latest = {}
        for a in agents:
            latest[a.id] = session.exec(
                select(Telemetry).where(Telemetry.agent_id == a.id).order_by(Telemetry.ts.desc()).limit(10)
            ).all()
        profiles = session.exec(select(Profile)).all()
    return templates.TemplateResponse(request, "agents.html", {"user": cu, "agents": agents, "latest": latest, "profiles": profiles})


@router.post("/agents/{agent_id}/apply")
def apply(agent_id: int, profile_id: int, user: str = "operator"):
    apply_profile(agent_id, profile_id, user)
    return RedirectResponse("/agents", status_code=303)


@router.post("/agents/{agent_id}/stop")
def stop(agent_id: int, user: str = "operator"):
    stop_profile(agent_id, user)
    return RedirectResponse("/agents", status_code=303)


@router.get("/profiles", response_class=HTMLResponse)
def profiles_page(request: Request, search: str = "", sort: str = "name", user: str | None = None):
    cu = current_user(user)
    with Session(engine) as session:
        query = select(Profile)
        if search:
            query = query.where(Profile.name.contains(search))
        order_col = Profile.name if sort == "name" else Profile.latency_factor
        profiles = session.exec(query.order_by(order_col)).all()
    return templates.TemplateResponse(request, "profiles.html", {"user": cu, "profiles": profiles})


@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, user_filter: str = "", action_filter: str = "", user: str | None = None):
    cu = current_user(user)
    with Session(engine) as session:
        query = select(AuditLog)
        if user_filter:
            query = query.where(AuditLog.user == user_filter)
        if action_filter:
            query = query.where(AuditLog.action == action_filter)
        logs = session.exec(query.order_by(AuditLog.ts.desc()).limit(200)).all()
    return templates.TemplateResponse(request, "audit.html", {"user": cu, "logs": logs})


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, user: str | None = None):
    cu = current_user(user)
    if cu.role not in {"viewer", "operator", "admin"}:
        return HTMLResponse("Forbidden", status_code=403)

    with Session(engine) as session:
        recent_audit = session.exec(select(AuditLog).order_by(AuditLog.ts.desc()).limit(25)).all()
        recent_t = session.exec(select(Telemetry).order_by(Telemetry.ts.desc()).limit(25)).all()
        summary = kpi(session, "24h")
    events = sorted(
        [{"ts": x.ts, "type": x.action, "details": x.details} for x in recent_audit]
        + [{"ts": x.ts, "type": x.scenario, "details": f"agent={x.agent_id}, err={x.errors}"} for x in recent_t],
        key=lambda item: item["ts"],
        reverse=True,
    )[:50]
    return templates.TemplateResponse(request, "analytics.html", {"user": cu, "summary": summary, "events": events})


@router.get("/tests", response_class=HTMLResponse)
def tests_page(request: Request, user: str | None = None):
    cu = current_user(user)
    with Session(engine) as session:
        rows = session.exec(select(TestRun).order_by(TestRun.ts.desc()).limit(100)).all()
    per_day: dict[str, list[bool]] = {}
    for row in rows:
        day = row.ts.strftime("%Y-%m-%d")
        per_day.setdefault(day, []).append(row.success)
    success_rate = [{"day": d, "rate": round(sum(vals) / len(vals) * 100, 1)} for d, vals in sorted(per_day.items())]
    return templates.TemplateResponse(request, "tests.html", {"user": cu, "rows": rows, "success_rate_json": json.dumps(success_rate)})
