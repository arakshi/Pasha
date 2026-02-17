from __future__ import annotations

from datetime import datetime, timedelta
import random

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Agent, AuditLog, Profile, Telemetry, TestRun, User

DATABASE_URL = "sqlite:///./control_panel.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


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
                    duration_ms=random.randint(900, 18_000),
                    success=success,
                    checks=";".join(checks),
                )
            )

        session.commit()
