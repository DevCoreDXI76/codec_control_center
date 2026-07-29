# app/main.py
"""FastAPI 진입점 (SPEC.md 1절/2절). 로컬 웹 대시보드 서버."""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes_control import router as control_router
from app.api.routes_devices import router as devices_router
from app.api.routes_logs import router as logs_router
from app.api.routes_settings import router as settings_router
from app.api.routes_teams import router as teams_router
from app.api.ws_status import StatusBroadcaster
from app.api.ws_status import router as ws_status_router
from app.core.driver_factory import build_driver_factory
from app.core.history import ControlHistory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.settings import SettingsStore
from app.core.vault import CredentialVault


def _resolve_paths() -> tuple[Path, Path, Path, Path]:
    """(app_dir, templates_dir, static_dir, data_dir)를 반환한다.

    PyInstaller onefile EXE(frozen)에서는 번들 리소스(templates/static)는
    sys._MEIPASS(실행 시 임시 압축해제 경로)에서 읽고, 사용자 데이터(data/)는
    실행 파일이 실제로 위치한 폴더에 만든다 — _MEIPASS는 프로세스 종료 시
    삭제되므로 거기에 데이터를 쓰면 재실행 때마다 레지스트리가 사라진다
    (SPEC.md 11절: "설치 폴더의 data/는 삭제하지 말 것" 전제와 일치시키기 위함).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = Path(sys._MEIPASS)
        exe_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent.parent
        exe_dir = base_dir

    app_dir = base_dir / "app"
    return app_dir, app_dir / "templates", app_dir / "static", exe_dir / "data"


APP_DIR, TEMPLATES_DIR, STATIC_DIR, DATA_DIR = _resolve_paths()


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
app.state.settings_store = SettingsStore(DATA_DIR / "settings.json")
app.state.settings = app.state.settings_store.load()
app.state.history = ControlHistory(DATA_DIR / "history.sqlite3")

app.state.scheduler = PollingScheduler(
    driver_factory=build_driver_factory(
        app.state.registry,
        app.state.vault,
        get_timeout=lambda: app.state.settings.command_timeout,
    ),
    base_interval=app.state.settings.poll_interval,
    max_concurrency=app.state.settings.max_concurrency,
    on_status=app.state.broadcaster.notify,
)

app.include_router(devices_router)
app.include_router(control_router)
app.include_router(teams_router)
app.include_router(settings_router)
app.include_router(logs_router)
app.include_router(ws_status_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def dashboard(request: Request):
    registry = request.app.state.registry
    scheduler = request.app.state.scheduler
    device_list = registry.list_devices()
    devices = [{"device": device, "status": scheduler.get_status(device.id)} for device in device_list]
    groups = sorted({device.group for device in device_list if device.group})
    return templates.TemplateResponse(request, "index.html", {"devices": devices, "groups": groups})


@app.get("/settings")
async def settings_page(request: Request):
    settings = request.app.state.settings_store.load()
    return templates.TemplateResponse(
        request, "settings.html", {"settings": settings, "data_dir": str(DATA_DIR)}
    )


@app.get("/logs")
async def logs_page(request: Request):
    entries = request.app.state.history.list_recent(limit=200)
    return templates.TemplateResponse(request, "logs.html", {"entries": entries})
