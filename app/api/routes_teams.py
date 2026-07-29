# app/api/routes_teams.py
"""Teams/OBTP API (SPEC.md 7절).

Cisco는 Bookings List의 JSON 필드 스키마는 확인했으나(레퍼런스: PepperDash
epi-videoCodec-ciscoExtended), 현재 CiscoDriver는 텍스트 모드로 구현되어 있어
JSON 스키마를 텍스트 모드로 억지로 끼워 맞추지 않는다 (추측 금지 원칙).
CiscoDriver.get_calendar_status/get_obtp_entries는 NotImplementedError를
던지며, 이 라우트는 그 경우 "미지원"으로 정직하게 응답한다.
"""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.driver_base import CalendarEntry, DriverError
from app.core.polling import PollingScheduler

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
    entry = CalendarEntry(
        subject=payload.subject,
        start_time=payload.start_time,
        end_time=payload.end_time,
        join_uri=payload.join_uri,
    )
    try:
        ok = await driver.join_meeting(entry)
    except DriverError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": ok}
