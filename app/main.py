# app/main.py
"""FastAPI 진입점 (SPEC.md 1절/2절). 로컬 웹 대시보드 서버."""
from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.__version__ import __version__
from app.api.routes_control import router as control_router
from app.api.routes_devices import router as devices_router
from app.api.routes_groups import router as groups_router
from app.api.routes_logs import router as logs_router
from app.api.routes_settings import router as settings_router
from app.api.routes_teams import router as teams_router
from app.api.ws_status import StatusBroadcaster
from app.api.ws_status import router as ws_status_router
from app.core.applog import tail_app_log
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


def _configure_logging(log_path: Path) -> None:
    """폴링/드라이버 접속 오류를 파일로 남긴다.

    UI 카드에는 최신 오류 메시지 한 줄만 보이고 지나간 이력은 사라지므로,
    실장비 검증(Phase③) 중 재현이 어려운 접속 문제를 나중에 분석할 수 있도록
    data/app.log에 누적 기록한다.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) and h.baseFilename == str(log_path) for h in root_logger.handlers):
        return  # 모듈이 이미 로드되어 핸들러가 설정된 경우 중복 등록 방지
    handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


APP_DIR, TEMPLATES_DIR, STATIC_DIR, DATA_DIR = _resolve_paths()
APP_LOG_PATH = DATA_DIR / "app.log"
_configure_logging(APP_LOG_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    for device in app.state.registry.list_devices():
        await app.state.scheduler.add_device(device.id)
    await app.state.scheduler.start()
    yield
    await app.state.scheduler.stop()


app = FastAPI(title="BridgeX", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.state.registry = DeviceRegistry(DATA_DIR / "devices.enc.json")
app.state.vault = CredentialVault(DATA_DIR / "credentials.enc.json")
app.state.broadcaster = StatusBroadcaster()
app.state.settings_store = SettingsStore(DATA_DIR / "settings.json")
app.state.settings = app.state.settings_store.load()
app.state.history = ControlHistory(DATA_DIR / "history.sqlite3")
app.state.app_log_path = APP_LOG_PATH

def _device_label(device_id: str) -> str:
    """로그용 — device_id(uuid) 대신 사람이 알아볼 수 있는 장비 이름을 남긴다."""
    device = app.state.registry.get_device(device_id)
    return device.name if device is not None else device_id


def _on_model_discovered(device_id: str, model: str) -> None:
    """폴링에서 처음 확보한 모델명을 레지스트리에 1회 반영한다 — 이미 같은 값이면 쓰지 않는다
    (매 폴링마다 DPAPI 암호화+파일 쓰기가 일어나는 걸 막기 위함)."""
    device = app.state.registry.get_device(device_id)
    if device is not None and device.model != model:
        app.state.registry.update_device(device_id, model=model)


app.state.scheduler = PollingScheduler(
    driver_factory=build_driver_factory(
        app.state.registry,
        app.state.vault,
        get_timeout=lambda: app.state.settings.command_timeout,
    ),
    base_interval=app.state.settings.poll_interval,
    max_concurrency=app.state.settings.max_concurrency,
    on_status=app.state.broadcaster.notify,
    get_device_label=_device_label,
    on_model_discovered=_on_model_discovered,
)

app.include_router(devices_router)
app.include_router(groups_router)
app.include_router(control_router)
app.include_router(teams_router)
app.include_router(settings_router)
app.include_router(logs_router)
app.include_router(ws_status_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/")
async def dashboard(request: Request):
    registry = request.app.state.registry
    scheduler = request.app.state.scheduler
    device_list = registry.list_devices()
    devices = [{"device": device, "status": scheduler.get_status(device.id)} for device in device_list]
    groups = sorted({device.group for device in device_list if device.group})
    return templates.TemplateResponse(
        request, "index.html", {"devices": devices, "groups": groups, "settings": request.app.state.settings}
    )


@app.get("/settings")
async def settings_page(request: Request):
    settings = request.app.state.settings_store.load()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": settings, "data_dir": str(DATA_DIR), "app_version": __version__},
    )


@app.get("/logs")
async def logs_page(request: Request):
    entries = request.app.state.history.list_recent(limit=200)
    copy_text = ""
    if entries:
        header = "\t".join(["시각", "장비", "동작", "결과", "상세"])
        rows = [
            "\t".join([e.created_at, e.device_name, e.action, "성공" if e.success else "실패", e.detail or ""])
            for e in entries
        ]
        copy_text = "\n".join([header, *rows])
    return templates.TemplateResponse(
        request, "logs.html", {"view": "control", "entries": entries, "copy_text": copy_text}
    )


@app.get("/logs/system")
async def system_log_page(request: Request):
    log_lines = tail_app_log(request.app.state.app_log_path)
    copy_text = "\n".join(log_lines)
    return templates.TemplateResponse(
        request, "logs.html", {"view": "system", "log_lines": log_lines, "copy_text": copy_text}
    )


@app.get("/guide")
async def guide_page(request: Request):
    return templates.TemplateResponse(request, "guide.html", {})
