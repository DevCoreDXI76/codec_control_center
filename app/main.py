# app/main.py
"""FastAPI 진입점 (SPEC.md 1절/2절). 로컬 웹 대시보드 서버."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes_control import router as control_router
from app.api.routes_devices import router as devices_router
from app.api.routes_teams import router as teams_router
from app.api.ws_status import StatusBroadcaster
from app.api.ws_status import router as ws_status_router
from app.core.driver_factory import build_driver_factory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
DATA_DIR = APP_DIR.parent / "data"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    for device in app.state.registry.list_devices():
        await app.state.scheduler.add_device(device.id)
    await app.state.scheduler.start()
    yield
    await app.state.scheduler.stop()


app = FastAPI(title="Codec Control Center", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.state.registry = DeviceRegistry(DATA_DIR / "devices.enc.json")
app.state.vault = CredentialVault(DATA_DIR / "credentials.enc.json")
app.state.broadcaster = StatusBroadcaster()
app.state.scheduler = PollingScheduler(
    driver_factory=build_driver_factory(app.state.registry, app.state.vault),
    on_status=app.state.broadcaster.notify,
)

app.include_router(devices_router)
app.include_router(control_router)
app.include_router(teams_router)
app.include_router(ws_status_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def dashboard(request: Request):
    registry = request.app.state.registry
    scheduler = request.app.state.scheduler
    devices = [
        {"device": device, "status": scheduler.get_status(device.id)}
        for device in registry.list_devices()
    ]
    return templates.TemplateResponse(request, "index.html", {"devices": devices})
