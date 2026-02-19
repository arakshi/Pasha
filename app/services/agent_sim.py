from __future__ import annotations

import asyncio
from datetime import datetime
import random

from sqlmodel import Session, select

from app.database import engine
from app.models import Agent, AuditLog, Profile, Telemetry


def _is_vless_profile(name: str) -> bool:
    return "vless" in name.lower()


async def telemetry_worker(interval_seconds: int = 7) -> None:
    while True:
        with Session(engine) as session:
            agents = session.exec(select(Agent).where(Agent.status == "online")).all()
            profiles = session.exec(select(Profile)).all()
            if profiles:
                for agent in agents:
                    profile = random.choice(profiles)
                    is_vless = _is_vless_profile(profile.name)
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
                            scenario="vless_simulated_tunnel" if is_vless else "heartbeat",
                            tunnel_mode="vless_simulated" if is_vless else "none",
                            handshake_ms=random.randint(18, 65) if is_vless else None,
                            jitter_ms=random.randint(2, 18) if is_vless else random.randint(1, 7),
                            route_hops=random.randint(5, 12) if is_vless else random.randint(2, 8),
                            packet_loss_pct=round(random.uniform(0.2, 1.8), 2) if is_vless else round(random.uniform(0.0, 0.6), 2),
                        )
                    )
                    agent.last_seen = datetime.utcnow()
            session.commit()
        await asyncio.sleep(interval_seconds)


def apply_profile(agent_id: int, profile_id: int, user: str) -> None:
    with Session(engine) as session:
        profile = session.get(Profile, profile_id)
        mode = "vless_simulated" if (profile and _is_vless_profile(profile.name)) else "none"
        session.add(
            AuditLog(
                user=user,
                action="APPLY_PROFILE",
                agent_id=agent_id,
                profile_id=profile_id,
                details=f"Профиль применён оператором | режим: {mode}",
            )
        )
        session.add(
            Telemetry(
                agent_id=agent_id,
                bytes_in=random.randint(30_000, 60_000),
                bytes_out=random.randint(28_000, 58_000),
                latency_ms=random.randint(35, 180),
                errors=random.randint(0, 1),
                profile_id=profile_id,
                scenario="apply_profile",
                tunnel_mode=mode,
                handshake_ms=random.randint(22, 80) if mode == "vless_simulated" else None,
                jitter_ms=random.randint(2, 12),
                route_hops=random.randint(4, 11),
                packet_loss_pct=round(random.uniform(0.1, 1.2), 2),
            )
        )
        session.commit()


def stop_profile(agent_id: int, user: str) -> None:
    with Session(engine) as session:
        session.add(
            AuditLog(
                user=user,
                action="STOP_PROFILE",
                agent_id=agent_id,
                details="Профиль остановлен оператором",
            )
        )
        session.add(
            Telemetry(
                agent_id=agent_id,
                bytes_in=random.randint(5_000, 20_000),
                bytes_out=random.randint(5_000, 18_000),
                latency_ms=random.randint(40, 210),
                errors=random.randint(0, 1),
                scenario="stop_profile",
                tunnel_mode="none",
                jitter_ms=random.randint(1, 7),
                route_hops=random.randint(2, 8),
                packet_loss_pct=round(random.uniform(0.0, 0.6), 2),
            )
        )
        session.commit()
