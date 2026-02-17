from __future__ import annotations

from datetime import datetime, timedelta
import random

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Agent, AuditLog, Profile, Telemetry, TestRun, User

DATABASE_URL = "sqlite:///./control_panel.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


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
            Profile(name="Balanced", latency_factor=1.0, error_factor=1.0, throughput_factor=1.0, description="Default profile."),
            Profile(name="Low-Latency", latency_factor=0.7, error_factor=1.2, throughput_factor=0.9, description="Lower latency, slightly higher errors."),
            Profile(name="High-Throughput", latency_factor=1.3, error_factor=1.1, throughput_factor=1.8, description="High transfer mode."),
            Profile(name="Safe", latency_factor=1.1, error_factor=0.6, throughput_factor=0.8, description="Stability focused."),
            Profile(name="Experimental", latency_factor=1.4, error_factor=1.6, throughput_factor=1.2, description="For test-only simulation."),
        ]
        session.add_all(profiles)
        session.flush()

        agents = [
            Agent(name="edge-eu-01", status="online"),
            Agent(name="edge-eu-02", status="online"),
            Agent(name="edge-us-01", status="online"),
            Agent(name="edge-us-02", status="offline"),
            Agent(name="edge-ap-01", status="online"),
            Agent(name="edge-ap-02", status="offline"),
            Agent(name="edge-lab-01", status="online"),
        ]
        session.add_all(agents)
        session.flush()

        now = datetime.utcnow()
        for minute in range(60, 0, -1):
            ts = now - timedelta(minutes=minute)
            for agent in agents:
                if agent.status != "online":
                    continue
                profile = random.choice(profiles)
                bytes_in = int(random.randint(10_000, 80_000) * profile.throughput_factor)
                bytes_out = int(random.randint(8_000, 70_000) * profile.throughput_factor)
                latency = int(random.randint(40, 220) * profile.latency_factor)
                errors = max(0, int(random.randint(0, 3) * profile.error_factor) - 1)
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
        users = ["admin", "operator", "viewer"]
        for i in range(90):
            ts = now - timedelta(hours=random.randint(0, 72), minutes=random.randint(0, 59))
            action = random.choice(actions)
            agent = random.choice(agents)
            profile = random.choice(profiles)
            session.add(
                AuditLog(
                    ts=ts,
                    user=random.choice(users),
                    action=action,
                    agent_id=agent.id,
                    profile_id=profile.id if action != "PING" else None,
                    details=f"Generated {action.lower()} event",
                )
            )

        for i in range(30):
            ts = now - timedelta(days=random.randint(0, 13), hours=random.randint(0, 23))
            success = random.random() > 0.2
            checks = "connectivity,latency,policy,consistency"
            session.add(
                TestRun(
                    ts=ts,
                    run_name=f"regression-suite-{i+1}",
                    duration_ms=random.randint(350, 4500),
                    success=success,
                    checks=checks,
                )
            )

        session.commit()
