# app/api/routes_control.py
"""장비 상태 조회/제어 API (SPEC.md 7절) — PollingScheduler가 관리하는 세션을 재사용한다."""
from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.driver_base import DeviceDriver, DriverError
from app.core.polling import PollingScheduler

router = APIRouter(prefix="/api/devices", tags=["control"])


class MuteRequest(BaseModel):
    on: bool


class DialRequest(BaseModel):
    address: str


def _get_scheduler(request: Request) -> PollingScheduler:
    return request.app.state.scheduler


@router.get("/{device_id}/status")
async def get_status(device_id: str, request: Request) -> dict:
    scheduler = _get_scheduler(request)
    try:
        status = await scheduler.poll_once(device_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    return dataclasses.asdict(status)


@router.post("/{device_id}/mute")
async def mute(device_id: str, payload: MuteRequest, request: Request) -> dict:
    return await _run_control(request, device_id, lambda driver: driver.mute(payload.on))


@router.post("/{device_id}/dial")
async def dial(device_id: str, payload: DialRequest, request: Request) -> dict:
    return await _run_control(request, device_id, lambda driver: driver.dial(payload.address))


@router.post("/{device_id}/hangup")
async def hangup(device_id: str, request: Request) -> dict:
    return await _run_control(request, device_id, lambda driver: driver.hangup())


@router.post("/{device_id}/reboot")
async def reboot(device_id: str, request: Request) -> dict:
    return await _run_control(request, device_id, lambda driver: driver.reboot())


async def _run_control(
    request: Request, device_id: str, action: Callable[[DeviceDriver], Awaitable[bool]]
) -> dict:
    scheduler = _get_scheduler(request)
    try:
        driver = await scheduler.get_driver(device_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    try:
        ok = await action(driver)
    except DriverError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": ok}
