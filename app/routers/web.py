from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import engine
from app.models import Agent, AuditLog, Profile, Telemetry, TestRun, User
from app.services.agent_sim import apply_profile, stop_profile
from app.services.metrics import kpi

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

PAGE_TITLES = {
    "dashboard": "Главная панель",
    "agents": "Агенты",
    "profiles": "Профили",
    "audit": "Журнал аудита",
    "analytics": "Аналитика",
    "tests": "Тестовые прогоны",
}


def current_user(username: str | None) -> User:
    name = username or "admin"
    with Session(engine) as session:
        found = session.exec(select(User).where(User.username == name)).first()
        if found:
            return found
        return session.exec(select(User)).first()


def _all_users() -> list[User]:
    with Session(engine) as session:
        return session.exec(select(User).order_by(User.username)).all()


def _base_context(page_key: str, user_obj: User) -> dict:
    return {
        "user": user_obj,
        "active_user": user_obj.username,
        "users_for_switch": _all_users(),
        "title": PAGE_TITLES[page_key],
    }


def _analytics_explanations(summary: dict) -> list[str]:
    notes = []
    if summary["availability"] >= 85:
        notes.append("Доступность высокая: большая часть агентов онлайн и стабильно передаёт метрики.")
    else:
        notes.append("Доступность просела: стоит проверить офлайн-агентов и актуальность профилей.")

    if summary["error_rate"] <= 8:
        notes.append("Уровень ошибок низкий и находится в пределах нормы для производственной нагрузки.")
    else:
        notes.append("Уровень ошибок выше нормы: рекомендуется переключить часть агентов в стабильный профиль.")

    if summary["p95_latency_24h"] <= 130:
        notes.append("95-й перцентиль задержки комфортный — пользователи будут видеть быстрый отклик.")
    else:
        notes.append("Есть хвост по задержке (p95 повышен): проверьте регионы с пиковым трафиком.")
    return notes


@router.get("/", response_class=HTMLResponse)
def root(request: Request):
    return RedirectResponse("/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: str | None = None):
    cu = current_user(user)
    with Session(engine) as session:
        summary = kpi(session, "24h")
        trend = session.exec(select(Telemetry).order_by(Telemetry.ts.desc()).limit(45)).all()

    context = _base_context("dashboard", cu)
    context.update(
        {
            "summary": summary,
            "trend_json": json.dumps(
                [{"ts": t.ts.strftime("%H:%M"), "in": t.bytes_in, "out": t.bytes_out, "lat": t.latency_ms} for t in reversed(trend)]
            ),
        }
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


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
            latest[a.id] = session.exec(select(Telemetry).where(Telemetry.agent_id == a.id).order_by(Telemetry.ts.desc()).limit(10)).all()
        profiles = session.exec(select(Profile)).all()

    context = _base_context("agents", cu)
    context.update({"agents": agents, "latest": latest, "profiles": profiles, "search": search, "status": status, "sort": sort})
    return templates.TemplateResponse(request, "agents.html", context)


@router.post("/agents/{agent_id}/apply")
def apply(agent_id: int, profile_id: int = Form(...), user: str = Form("operator")):
    apply_profile(agent_id, profile_id, user)
    return RedirectResponse(f"/agents?{urlencode({'user': user})}", status_code=303)


@router.post("/agents/{agent_id}/stop")
def stop(agent_id: int, user: str = Form("operator")):
    stop_profile(agent_id, user)
    return RedirectResponse(f"/agents?{urlencode({'user': user})}", status_code=303)


@router.get("/profiles", response_class=HTMLResponse)
def profiles_page(request: Request, search: str = "", sort: str = "name", user: str | None = None):
    cu = current_user(user)
    with Session(engine) as session:
        query = select(Profile)
        if search:
            query = query.where(Profile.name.contains(search))
        order_col = Profile.name if sort == "name" else Profile.latency_factor
        profiles = session.exec(query.order_by(order_col)).all()

    context = _base_context("profiles", cu)
    context.update({"profiles": profiles, "search": search, "sort": sort})
    return templates.TemplateResponse(request, "profiles.html", context)


@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, user_filter: str = "", action_filter: str = "", user: str | None = None):
    cu = current_user(user)
    normalized_action = action_filter.strip().upper()

    with Session(engine) as session:
        query = select(AuditLog)
        if user_filter.strip():
            query = query.where(AuditLog.user.contains(user_filter.strip()))
        if normalized_action:
            query = query.where(AuditLog.action == normalized_action)
        logs = session.exec(query.order_by(AuditLog.ts.desc()).limit(250)).all()
        users = sorted(set(session.exec(select(AuditLog.user)).all()))

    context = _base_context("audit", cu)
    context.update({"logs": logs, "user_filter": user_filter, "action_filter": normalized_action, "users": users, "actions": ["PING", "APPLY_PROFILE", "STOP_PROFILE"]})
    return templates.TemplateResponse(request, "audit.html", context)


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, user: str | None = None):
    cu = current_user(user)
    if cu.role not in {"viewer", "operator", "admin"}:
        return HTMLResponse("Доступ запрещён", status_code=403)

    with Session(engine) as session:
        recent_audit = session.exec(select(AuditLog).order_by(AuditLog.ts.desc()).limit(35)).all()
        recent_t = session.exec(select(Telemetry).order_by(Telemetry.ts.desc()).limit(35)).all()
        summary = kpi(session, "24h")

    events = sorted(
        [{"ts": x.ts, "type": x.action, "details": x.details} for x in recent_audit]
        + [{"ts": x.ts, "type": x.scenario, "details": f"Агент={x.agent_id}, задержка={x.latency_ms} мс, ошибки={x.errors}"} for x in recent_t],
        key=lambda item: item["ts"],
        reverse=True,
    )[:50]

    context = _base_context("analytics", cu)
    context.update({"summary": summary, "events": events, "explanations": _analytics_explanations(summary)})
    return templates.TemplateResponse(request, "analytics.html", context)


@router.get("/tests", response_class=HTMLResponse)
def tests_page(request: Request, user: str | None = None):
    cu = current_user(user)
    with Session(engine) as session:
        rows = session.exec(select(TestRun).order_by(TestRun.ts.desc()).limit(150)).all()

    per_day: dict[str, list[bool]] = {}
    expanded = []
    for row in rows:
        day = row.ts.strftime("%Y-%m-%d")
        per_day.setdefault(day, []).append(row.success)
        checks = [chunk for chunk in row.checks.split(";") if chunk]
        expanded.append({"row": row, "checks": checks, "duration_s": round(row.duration_ms / 1000, 2)})

    success_rate = [{"day": d, "rate": round(sum(vals) / len(vals) * 100, 1)} for d, vals in sorted(per_day.items())]
    avg_duration_s = round((sum(r.duration_ms for r in rows) / len(rows)) / 1000, 2) if rows else 0
    fails = len([r for r in rows if not r.success])

    context = _base_context("tests", cu)
    context.update({"rows": expanded, "avg_duration_s": avg_duration_s, "fails": fails, "success_rate_json": json.dumps(success_rate)})
    return templates.TemplateResponse(request, "tests.html", context)
