from __future__ import annotations

import asyncio
import csv
import io
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Field, SQLModel, Session, create_engine, select

# =========================================================
# 1) Настройки и приложение
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
DB_URL = "sqlite:///./control_panel.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})

app = FastAPI(title="Панель управления")
static_dir = BASE_DIR / "app" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

PAGE_TITLES = {
    "dashboard": "Главная панель",
    "agents": "Агенты",
    "profiles": "Профили",
    "audit": "Журнал аудита",
    "analytics": "Аналитика",
    "tests": "Тестовые прогоны",
}

# =========================================================
# 2) Модели
# =========================================================
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    role: str = Field(index=True)


class Agent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    status: str = Field(default="offline", index=True)
    last_seen: datetime = Field(default_factory=datetime.utcnow, index=True)


class Profile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    latency_factor: float = 1.0
    error_factor: float = 1.0
    throughput_factor: float = 1.0
    description: str = ""


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    user: str = Field(index=True)
    action: str = Field(index=True)
    agent_id: Optional[int] = Field(default=None, index=True)
    profile_id: Optional[int] = Field(default=None, index=True)
    details: str = ""


class Telemetry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    agent_id: int = Field(index=True, foreign_key="agent.id")
    bytes_in: int
    bytes_out: int
    latency_ms: int
    errors: int
    profile_id: Optional[int] = Field(default=None, foreign_key="profile.id")
    scenario: str = Field(default="heartbeat", index=True)


class TestRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    run_name: str
    duration_ms: int
    success: bool
    checks: str

# =========================================================
# 3) Инициализация/seed
# =========================================================
def _agent_baseline(agent_name: str) -> tuple[int, int, int]:
    if "msk" in agent_name:
        return (90_000, 85_000, 35)
    if "spb" in agent_name:
        return (80_000, 78_000, 42)
    if "kzn" in agent_name:
        return (72_000, 69_000, 48)
    if "nsk" in agent_name:
        return (60_000, 58_000, 66)
    if "vvo" in agent_name:
        return (54_000, 50_000, 82)
    return (46_000, 44_000, 95)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.exec(select(User)).first():
            return

        session.add_all(
            [
                User(username="admin", role="admin"),
                User(username="operator", role="operator"),
                User(username="viewer", role="viewer"),
            ]
        )

        profiles = [
            Profile(name="Сбалансированный", latency_factor=1.0, error_factor=1.0, throughput_factor=1.0, description="Ровный профиль для типовой нагрузки."),
            Profile(name="Низкая задержка", latency_factor=0.72, error_factor=1.15, throughput_factor=0.92, description="Приоритет времени отклика."),
            Profile(name="Высокая пропускная", latency_factor=1.25, error_factor=1.1, throughput_factor=1.85, description="Максимум трафика под стабильные каналы."),
            Profile(name="Стабильный", latency_factor=1.08, error_factor=0.62, throughput_factor=0.82, description="Снижение ошибок ценой скорости."),
            Profile(name="Пиковая нагрузка", latency_factor=1.38, error_factor=1.5, throughput_factor=1.22, description="Режим для стрессовых часов."),
            Profile(name="Ночной режим", latency_factor=0.92, error_factor=0.74, throughput_factor=0.88, description="Умеренный режим для фона."),
        ]
        session.add_all(profiles)
        session.flush()

        agents = [
            Agent(name="edge-msk-01", status="online"),
            Agent(name="edge-msk-02", status="online"),
            Agent(name="edge-spb-01", status="online"),
            Agent(name="edge-kzn-01", status="online"),
            Agent(name="edge-nsk-01", status="online"),
            Agent(name="edge-vvo-01", status="offline"),
            Agent(name="edge-ekb-01", status="online"),
            Agent(name="edge-lab-01", status="offline"),
        ]
        now = datetime.utcnow()
        for ag in agents:
            ag.last_seen = now - timedelta(seconds=random.randint(10, 200 if ag.status == "online" else 5400))
        session.add_all(agents)
        session.flush()

        for minute in range(60 * 12, 0, -1):
            ts = now - timedelta(minutes=minute)
            active_ratio = 0.65 if 7 <= ts.hour <= 23 else 0.38
            for agent in agents:
                if agent.status != "online" and random.random() > 0.22:
                    continue
                if random.random() > active_ratio:
                    continue

                profile = random.choice(profiles)
                base_in, base_out, base_latency = _agent_baseline(agent.name)
                hourly_factor = 1.35 if 10 <= ts.hour <= 20 else 0.78
                noise = random.uniform(0.75, 1.25)

                bytes_in = int(base_in * hourly_factor * noise * profile.throughput_factor)
                bytes_out = int(base_out * hourly_factor * noise * profile.throughput_factor)
                latency = int(base_latency * random.uniform(0.85, 1.35) * profile.latency_factor)

                error_probability = 0.016 * profile.error_factor
                errors = random.randint(1, 3) if random.random() < error_probability else 0

                session.add(
                    Telemetry(
                        ts=ts,
                        agent_id=agent.id,
                        bytes_in=bytes_in,
                        bytes_out=bytes_out,
                        latency_ms=latency,
                        errors=errors,
                        profile_id=profile.id,
                        scenario="heartbeat",
                    )
                )

        actions = ["PING", "APPLY_PROFILE", "STOP_PROFILE"]
        action_weights = [0.62, 0.26, 0.12]
        users = ["admin", "operator", "viewer"]
        for _ in range(230):
            ts = now - timedelta(hours=random.randint(0, 72), minutes=random.randint(0, 59))
            action = random.choices(actions, weights=action_weights, k=1)[0]
            agent = random.choice(agents)
            profile = random.choice(profiles)
            session.add(
                AuditLog(
                    ts=ts,
                    user=random.choices(users, weights=[0.2, 0.55, 0.25], k=1)[0],
                    action=action,
                    agent_id=agent.id,
                    profile_id=profile.id if action != "PING" else None,
                    details=f"Событие: {action.lower()} | агент: {agent.name}",
                )
            )

        checks_base = ["Связность", "Задержка", "Маршруты", "Согласованность", "Политики", "Профиль"]
        for i in range(140):
            ts = now - timedelta(days=random.randint(0, 34), hours=random.randint(0, 23), minutes=random.randint(0, 59))
            load_peak = 1 if 9 <= ts.hour <= 21 else 0
            success = random.random() > (0.23 if load_peak else 0.12)
            checks = []
            for c in checks_base:
                state = "OK" if random.random() > (0.09 if success else 0.34) else "FAIL"
                checks.append(f"{c}:{state}")
            session.add(
                TestRun(
                    ts=ts,
                    run_name=f"Плановый прогон #{i + 1}",
                    duration_ms=random.randint(250, 4200),
                    success=success,
                    checks=";".join(checks),
                )
            )

        session.commit()

# =========================================================
# 4) Симулятор
# =========================================================
async def telemetry_worker(interval_seconds: int = 7) -> None:
    while True:
        with Session(engine) as session:
            agents = session.exec(select(Agent).where(Agent.status == "online")).all()
            profiles = session.exec(select(Profile)).all()
            if profiles:
                for agent in agents:
                    profile = random.choice(profiles)
                    bytes_in = int(random.randint(35_000, 115_000) * profile.throughput_factor * random.uniform(0.8, 1.2))
                    bytes_out = int(random.randint(33_000, 107_000) * profile.throughput_factor * random.uniform(0.8, 1.2))
                    latency = int(random.randint(28, 160) * profile.latency_factor * random.uniform(0.9, 1.25))
                    errors = 1 if random.random() < (0.02 * profile.error_factor) else 0
                    session.add(
                        Telemetry(
                            ts=datetime.utcnow(),
                            agent_id=agent.id,
                            bytes_in=bytes_in,
                            bytes_out=bytes_out,
                            latency_ms=latency,
                            errors=errors,
                            profile_id=profile.id,
                            scenario="heartbeat",
                        )
                    )
                    agent.last_seen = datetime.utcnow()
            session.commit()
        await asyncio.sleep(interval_seconds)


def apply_profile(agent_id: int, profile_id: int, user: str) -> None:
    with Session(engine) as session:
        session.add(AuditLog(user=user, action="APPLY_PROFILE", agent_id=agent_id, profile_id=profile_id, details="Профиль применён оператором"))
        session.add(
            Telemetry(
                agent_id=agent_id,
                bytes_in=random.randint(30_000, 60_000),
                bytes_out=random.randint(28_000, 58_000),
                latency_ms=random.randint(35, 180),
                errors=random.randint(0, 1),
                profile_id=profile_id,
                scenario="apply_profile",
            )
        )
        session.commit()


def stop_profile(agent_id: int, user: str) -> None:
    with Session(engine) as session:
        session.add(AuditLog(user=user, action="STOP_PROFILE", agent_id=agent_id, details="Профиль остановлен оператором"))
        session.add(
            Telemetry(
                agent_id=agent_id,
                bytes_in=random.randint(5_000, 20_000),
                bytes_out=random.randint(5_000, 18_000),
                latency_ms=random.randint(40, 210),
                errors=random.randint(0, 1),
                scenario="stop_profile",
            )
        )
        session.commit()

# =========================================================
# 5) Метрики
# =========================================================
RANGES = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}


def _start_for_range(range_name: str) -> datetime:
    return datetime.utcnow() - RANGES.get(range_name, timedelta(hours=24))


def _percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return float(ordered[idx])


def kpi(range_name: str) -> dict:
    with Session(engine) as session:
        start = _start_for_range(range_name)
        total_agents = len(session.exec(select(Agent)).all())
        online_agents = len(session.exec(select(Agent).where(Agent.status == "online")).all())

        deployments_24h = len(
            session.exec(select(AuditLog).where(AuditLog.action == "APPLY_PROFILE", AuditLog.ts >= datetime.utcnow() - timedelta(hours=24))).all()
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


# =========================================================
# 6) Веб-роуты
# =========================================================
def current_user(username: str | None) -> User:
    name = username or "admin"
    with Session(engine) as session:
        found = session.exec(select(User).where(User.username == name)).first()
        return found or session.exec(select(User)).first()


def all_users() -> list[User]:
    with Session(engine) as session:
        return session.exec(select(User).order_by(User.username)).all()


def ctx(page_key: str, user: User) -> dict:
    return {"title": PAGE_TITLES[page_key], "user": user, "active_user": user.username, "users_for_switch": all_users()}


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: str | None = None):
    cu = current_user(user)
    with Session(engine) as s:
        trend = s.exec(select(Telemetry).order_by(Telemetry.ts.desc()).limit(45)).all()
    c = ctx("dashboard", cu)
    c.update(
        {
            "request": request,
            "summary": kpi("24h"),
            "trend_json": json.dumps([{"ts": t.ts.strftime("%H:%M"), "in": t.bytes_in, "out": t.bytes_out, "lat": t.latency_ms} for t in reversed(trend)]),
        }
    )
    return templates.TemplateResponse(request, "dashboard.html", c)


@app.get("/agents", response_class=HTMLResponse)
def agents(request: Request, search: str = "", status: str = "all", sort: str = "desc", user: str | None = None):
    cu = current_user(user)
    with Session(engine) as s:
        q = select(Agent)
        if search:
            q = q.where(Agent.name.contains(search))
        if status in {"online", "offline"}:
            q = q.where(Agent.status == status)
        q = q.order_by(Agent.last_seen.desc() if sort == "desc" else Agent.last_seen.asc())
        agents_rows = s.exec(q).all()
        profiles = s.exec(select(Profile)).all()
        latest = {a.id: s.exec(select(Telemetry).where(Telemetry.agent_id == a.id).order_by(Telemetry.ts.desc()).limit(10)).all() for a in agents_rows}

    c = ctx("agents", cu)
    c.update({"request": request, "agents": agents_rows, "profiles": profiles, "latest": latest, "search": search, "status": status, "sort": sort})
    return templates.TemplateResponse(request, "agents.html", c)


@app.post("/agents/{agent_id}/apply")
def apply(agent_id: int, profile_id: int = Form(...), user: str = Form("operator")):
    apply_profile(agent_id, profile_id, user)
    return RedirectResponse(f"/agents?user={user}", status_code=303)


@app.post("/agents/{agent_id}/stop")
def stop(agent_id: int, user: str = Form("operator")):
    stop_profile(agent_id, user)
    return RedirectResponse(f"/agents?user={user}", status_code=303)


@app.get("/profiles", response_class=HTMLResponse)
def profiles(request: Request, search: str = "", sort: str = "name", user: str | None = None):
    cu = current_user(user)
    with Session(engine) as s:
        q = select(Profile)
        if search:
            q = q.where(Profile.name.contains(search))
        q = q.order_by(Profile.name if sort == "name" else Profile.latency_factor)
        profiles_rows = s.exec(q).all()
    c = ctx("profiles", cu)
    c.update({"request": request, "profiles": profiles_rows, "search": search, "sort": sort})
    return templates.TemplateResponse(request, "profiles.html", c)


@app.get("/audit", response_class=HTMLResponse)
def audit(request: Request, user_filter: str = "", action_filter: str = "", user: str | None = None):
    cu = current_user(user)
    action_filter = action_filter.strip().upper()
    with Session(engine) as s:
        q = select(AuditLog)
        if user_filter.strip():
            q = q.where(AuditLog.user.contains(user_filter.strip()))
        if action_filter:
            q = q.where(AuditLog.action == action_filter)
        logs = s.exec(q.order_by(AuditLog.ts.desc()).limit(250)).all()
        users = sorted(set(s.exec(select(AuditLog.user)).all()))
    c = ctx("audit", cu)
    c.update({"request": request, "logs": logs, "user_filter": user_filter, "action_filter": action_filter, "users": users, "actions": ["PING", "APPLY_PROFILE", "STOP_PROFILE"]})
    return templates.TemplateResponse(request, "audit.html", c)


@app.get("/analytics", response_class=HTMLResponse)
def analytics(request: Request, user: str | None = None):
    cu = current_user(user)
    if cu.role not in {"viewer", "operator", "admin"}:
        return HTMLResponse("Доступ запрещён", status_code=403)

    with Session(engine) as s:
        recent_audit = s.exec(select(AuditLog).order_by(AuditLog.ts.desc()).limit(35)).all()
        recent_t = s.exec(select(Telemetry).order_by(Telemetry.ts.desc()).limit(35)).all()

    events = sorted(
        [{"ts": x.ts, "type": x.action, "details": x.details} for x in recent_audit]
        + [{"ts": x.ts, "type": x.scenario, "details": f"Агент={x.agent_id}, задержка={x.latency_ms} мс, ошибки={x.errors}"} for x in recent_t],
        key=lambda item: item["ts"],
        reverse=True,
    )[:50]

    summary = kpi("24h")
    explanations = []
    explanations.append("Доступность высокая." if summary["availability"] >= 85 else "Доступность просела.")
    explanations.append("Ошибки в норме." if summary["error_rate"] <= 8 else "Ошибки выше нормы.")
    explanations.append("p95 комфортный." if summary["p95_latency_24h"] <= 130 else "p95 повышен.")

    c = ctx("analytics", cu)
    c.update({"request": request, "summary": summary, "events": events, "explanations": explanations})
    return templates.TemplateResponse(request, "analytics.html", c)


@app.get("/tests", response_class=HTMLResponse)
def tests(request: Request, user: str | None = None):
    cu = current_user(user)
    with Session(engine) as s:
        rows = s.exec(select(TestRun).order_by(TestRun.ts.desc()).limit(150)).all()

    per_day: dict[str, list[bool]] = {}
    expanded = []
    for row in rows:
        day = row.ts.strftime("%Y-%m-%d")
        per_day.setdefault(day, []).append(row.success)
        checks = [chunk for chunk in row.checks.split(";") if chunk]
        expanded.append({"row": row, "checks": checks, "duration_s": round(row.duration_ms / 1000, 2)})

    success_rate = [{"day": d, "rate": round(sum(vals) / len(vals) * 100, 1)} for d, vals in sorted(per_day.items())]
    avg_duration_s = round((sum(r.duration_ms for r in rows) / len(rows)) / 1000, 2) if rows else 0

    c = ctx("tests", cu)
    c.update({"request": request, "rows": expanded, "avg_duration_s": avg_duration_s, "fails": len([r for r in rows if not r.success]), "success_rate_json": json.dumps(success_rate)})
    return templates.TemplateResponse(request, "tests.html", c)

# =========================================================
# 7) API-метрики
# =========================================================
@app.get("/api/metrics/kpi")
def api_kpi(range: str = Query("24h")):
    return kpi(range)


@app.get("/api/metrics/traffic")
def api_traffic(range: str = Query("1h")):
    start = _start_for_range(range)
    with Session(engine) as s:
        rows = s.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"bytes_in": 0, "bytes_out": 0})
    for row in rows:
        key = row.ts.strftime("%d.%m %H:%M")
        grouped[key]["bytes_in"] += row.bytes_in
        grouped[key]["bytes_out"] += row.bytes_out
    labels = sorted(grouped.keys())
    return {"labels": labels, "bytes_in": [grouped[k]["bytes_in"] for k in labels], "bytes_out": [grouped[k]["bytes_out"] for k in labels]}


@app.get("/api/metrics/latency")
def api_latency(range: str = Query("1h")):
    start = _start_for_range(range)
    with Session(engine) as s:
        rows = s.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        grouped[row.ts.strftime("%d.%m %H:%M")].append(row.latency_ms)
    labels = sorted(grouped.keys())
    return {"labels": labels, "latency": [round(sum(grouped[k]) / len(grouped[k]), 2) for k in labels]}


@app.get("/api/metrics/actions")
def api_actions(range: str = Query("24h")):
    _ = range
    start = datetime.utcnow() - timedelta(hours=24)
    with Session(engine) as s:
        rows = s.exec(select(AuditLog).where(AuditLog.ts >= start)).all()
    mapped = {"PING": 0, "APPLY": 0, "STOP": 0}
    for row in rows:
        if row.action == "PING":
            mapped["PING"] += 1
        elif row.action == "APPLY_PROFILE":
            mapped["APPLY"] += 1
        elif row.action == "STOP_PROFILE":
            mapped["STOP"] += 1
    return {"labels": list(mapped.keys()), "values": list(mapped.values())}


@app.get("/api/metrics/profile_distribution")
def api_profile_distribution(range: str = Query("7d")):
    start = _start_for_range(range)
    with Session(engine) as s:
        rows = s.exec(select(AuditLog).where(AuditLog.action == "APPLY_PROFILE", AuditLog.ts >= start)).all()
        profile_map = {p.id: p.name for p in s.exec(select(Profile)).all()}
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


@app.get("/api/metrics/top_errors")
def api_top_errors(range: str = Query("24h")):
    _ = range
    start = datetime.utcnow() - timedelta(hours=24)
    with Session(engine) as s:
        rows = s.exec(select(Telemetry).where(Telemetry.ts >= start)).all()
        agent_map = {a.id: a.name for a in s.exec(select(Agent)).all()}
    counts: dict[int, int] = defaultdict(int)
    for row in rows:
        counts[row.agent_id] += row.errors
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:7]
    return {"labels": [agent_map.get(a, f"agent_{a}") for a, _ in sorted_items], "values": [v for _, v in sorted_items]}


@app.get("/api/telemetry/export.csv")
def export_telemetry(range: str = Query("24h")):
    now = datetime.utcnow()
    start = now - timedelta(hours=24) if range == "24h" else (now - timedelta(hours=1) if range == "1h" else now - timedelta(days=7))
    with Session(engine) as session:
        rows = session.exec(select(Telemetry).where(Telemetry.ts >= start).order_by(Telemetry.ts.desc())).all()

    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["id", "ts", "agent_id", "bytes_in", "bytes_out", "latency_ms", "errors", "profile_id", "scenario"])
    for r in rows:
        writer.writerow([r.id, r.ts.isoformat(), r.agent_id, r.bytes_in, r.bytes_out, r.latency_ms, r.errors, r.profile_id, r.scenario])
    stream.seek(0)

    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=telemetry_export.csv"})


@app.on_event("startup")
async def startup() -> None:
    init_db()
    asyncio.create_task(telemetry_worker())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app_single_file:app", host="127.0.0.1", port=8000, reload=True)
