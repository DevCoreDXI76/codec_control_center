# app/api/routes_settings.py
"""설정 API (UX_SPEC.md 4.6절). 폴링 주기/동시 접속 제한/명령 타임아웃 조회·저장."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.settings import AppSettings, SettingsStore

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdateRequest(BaseModel):
    poll_interval: float
    max_concurrency: int
    command_timeout: float
    open_browser_on_start: bool
    teams_tenant_address: str = ""


def _get_store(request: Request) -> SettingsStore:
    return request.app.state.settings_store


@router.get("")
async def get_settings(request: Request) -> dict:
    return asdict(_get_store(request).load())


@router.put("")
async def update_settings(payload: SettingsUpdateRequest, request: Request) -> dict:
    try:
        settings = AppSettings(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _get_store(request).save(settings)
    request.app.state.settings = settings

    scheduler = request.app.state.scheduler
    scheduler.base_interval = settings.poll_interval
    scheduler.update_concurrency(settings.max_concurrency)

    return asdict(settings)
