# app/api/routes_control.py
"""장비 상태 조회/제어 API (SPEC.md 7절) — PollingScheduler가 관리하는 세션을 재사용한다."""
from __future__ import annotations

import dataclasses
import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.driver_base import DeviceDriver, DriverError
from app.core.history import ControlHistory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["control"])


class MuteRequest(BaseModel):
    on: bool


class DialRequest(BaseModel):
    address: str


def _get_scheduler(request: Request) -> PollingScheduler:
    return request.app.state.scheduler


def _get_history(request: Request) -> ControlHistory:
    return request.app.state.history


def _get_registry(request: Request) -> DeviceRegistry:
    return request.app.state.registry


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
    action = "mute" if payload.on else "unmute"
    return await _run_control(request, device_id, action, lambda driver: driver.mute(payload.on))


@router.post("/{device_id}/dial")
async def dial(device_id: str, payload: DialRequest, request: Request) -> dict:
    return await _run_control(
        request, device_id, "dial", lambda driver: driver.dial(payload.address), detail=payload.address
    )


@router.post("/{device_id}/hangup")
async def hangup(device_id: str, request: Request) -> dict:
    return await _run_control(request, device_id, "hangup", lambda driver: driver.hangup())


@router.post("/{device_id}/reboot")
async def reboot(device_id: str, request: Request) -> dict:
    return await _run_control(request, device_id, "reboot", lambda driver: driver.reboot())


async def _run_control(
    request: Request,
    device_id: str,
    action_name: str,
    action: Callable[[DeviceDriver], Awaitable[bool]],
    detail: str | None = None,
) -> dict:
    scheduler = _get_scheduler(request)
    history = _get_history(request)
    device = _get_registry(request).get_device(device_id)
    device_name = device.name if device is not None else device_id

    try:
        ok = await scheduler.run_with_driver(device_id, action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except DriverError as exc:
        logger.warning("device %s %s failed: %s", device_name, action_name, exc)
        history.log(device_id=device_id, device_name=device_name, action=action_name, success=False, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # DriverError가 아닌 예상 밖 예외 — 트레이스백까지 남기고 이력에도 기록한 뒤 502로 응답한다.
        logger.exception("device %s %s raised unexpected error", device_name, action_name)
        history.log(
            device_id=device_id, device_name=device_name, action=action_name, success=False, detail=str(exc)
        )
        raise HTTPException(status_code=502, detail=f"unexpected error: {exc}") from exc

    history.log(device_id=device_id, device_name=device_name, action=action_name, success=ok, detail=detail)
    return {"ok": ok}
