from __future__ import annotations

import asyncio
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import api, web
from app.services.agent_sim import telemetry_worker

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Control Panel")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(api.router)
app.include_router(web.router)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    asyncio.create_task(telemetry_worker())


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
