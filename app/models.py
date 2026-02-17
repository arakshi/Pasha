from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


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
