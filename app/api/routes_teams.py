# app/api/routes_teams.py
"""Teams/OBTP API (SPEC.md 7절).

Cisco 대상 모델 확정(Room Kit/Room Kit Pro/Room Kit EQ/Room Bar/Room Bar Pro, 2026-07-29)
이후 get_calendar_status는 공식 문서로 확인된 xStatus Bookings Availability Status로 구현했다.
get_obtp_entries(회의 상세)는 Bookings List/Get 응답의 정확한 텍스트 필드 레이아웃이
공식 문서에 예시가 없어 최선으로 추정한 것이며 Phase③ 실장비 검증 전까지 확정이 아니다
(app/drivers/cisco/cisco_commands.py 주석 참고). 그래도 명령 자체가 실패하면(NotImplementedError가
아닌 DriverError) 이 라우트는 502로 응답한다 — "미지원"은 이제 발생하지 않는다.
"""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.driver_base import CalendarEntry, DriverError
from app.core.history import ControlHistory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry

router = APIRouter(prefix="/api/devices", tags=["teams"])


class JoinRequest(BaseModel):
    subject: str
    start_time: str
    end_time: str
    join_uri: str | None = None


def _get_scheduler(request: Request) -> PollingScheduler:
    return request.app.state.scheduler


async def _get_driver(request: Request, device_id: str):
    try:
        return await _get_scheduler(request).get_driver(device_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc


@router.get("/{device_id}/calendar")
async def get_calendar(device_id: str, request: Request) -> dict:
    driver = await _get_driver(request, device_id)
    try:
        status = await driver.get_calendar_status()
    except NotImplementedError:
        return {"supported": False, "status": None}
    except DriverError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"supported": True, "status": status}


@router.get("/{device_id}/obtp")
async def get_obtp(device_id: str, request: Request) -> dict:
    driver = await _get_driver(request, device_id)
    try:
        entries = await driver.get_obtp_entries()
    except NotImplementedError:
        return {"supported": False, "entries": []}
    except DriverError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"supported": True, "entries": [dataclasses.asdict(e) for e in entries]}


@router.post("/{device_id}/join")
async def join_meeting(device_id: str, payload: JoinRequest, request: Request) -> dict:
    driver = await _get_driver(request, device_id)
    history: ControlHistory = request.app.state.history
    registry: DeviceRegistry = request.app.state.registry
    device = registry.get_device(device_id)
    device_name = device.name if device is not None else device_id

    entry = CalendarEntry(
        subject=payload.subject,
        start_time=payload.start_time,
        end_time=payload.end_time,
        join_uri=payload.join_uri,
    )
    try:
        ok = await driver.join_meeting(entry)
    except DriverError as exc:
        history.log(device_id=device_id, device_name=device_name, action="join", success=False, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history.log(device_id=device_id, device_name=device_name, action="join", success=ok, detail=payload.subject)
    return {"ok": ok}
