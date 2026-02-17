from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import api, web
from app.services.agent_sim import telemetry_worker

app = FastAPI(title="Sim Control Panel")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api.router)
app.include_router(web.router)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    asyncio.create_task(telemetry_worker())
