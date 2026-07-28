# app/main.py
"""FastAPI 진입점 (SPEC.md 1절/2절). 로컬 웹 대시보드 서버."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes_devices import router as devices_router
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
DATA_DIR = APP_DIR.parent / "data"

app = FastAPI(title="Codec Control Center")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.state.registry = DeviceRegistry(DATA_DIR / "devices.enc.json")
app.state.vault = CredentialVault(DATA_DIR / "credentials.enc.json")

app.include_router(devices_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
