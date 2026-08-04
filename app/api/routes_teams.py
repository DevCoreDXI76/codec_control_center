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
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.driver_base import CalendarEntry, DriverConflictError, DriverError
from app.api.routes_control import reject_if_in_call
from app.core.history import ControlHistory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["teams"])


class JoinRequest(BaseModel):
    subject: str
    start_time: str
    end_time: str
    join_uri: str | None = None


class DirectDialRequest(BaseModel):
    meeting_id: str
    tenant_address: str | None = None


_MEETING_ID_RE = re.compile(r"^\d{10}\Z")
_TENANT_ADDRESS_FORBIDDEN_CHARS = ('"', "'", "\r", "\n")


def _get_scheduler(request: Request) -> PollingScheduler:
    return request.app.state.scheduler


@router.get("/{device_id}/calendar")
async def get_calendar(device_id: str, request: Request) -> dict:
    try:
        status = await _get_scheduler(request).run_with_driver(device_id, lambda driver: driver.get_calendar_status())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except NotImplementedError:
        return {"supported": False, "status": None}
    except DriverError as exc:
        logger.warning("device %s calendar status failed: %s", device_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"supported": True, "status": status}


@router.get("/{device_id}/obtp")
async def get_obtp(device_id: str, request: Request) -> dict:
    try:
        entries = await _get_scheduler(request).run_with_driver(device_id, lambda driver: driver.get_obtp_entries())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except NotImplementedError:
        return {"supported": False, "entries": []}
    except DriverError as exc:
        logger.warning("device %s obtp fetch failed: %s", device_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"supported": True, "entries": [dataclasses.asdict(e) for e in entries]}


@router.post("/{device_id}/join")
async def join_meeting(device_id: str, payload: JoinRequest, request: Request) -> dict:
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

    async def guarded(driver):
        await reject_if_in_call(driver)
        return await driver.join_meeting(entry)

    try:
        ok = await _get_scheduler(request).run_with_driver(device_id, guarded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except DriverConflictError as exc:
        history.log(device_id=device_id, device_name=device_name, action="join", success=False, detail=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DriverError as exc:
        history.log(device_id=device_id, device_name=device_name, action="join", success=False, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history.log(device_id=device_id, device_name=device_name, action="join", success=ok, detail=payload.subject)
    return {"ok": ok}


@router.post("/{device_id}/direct-dial")
async def direct_dial(device_id: str, payload: DirectDialRequest, request: Request) -> dict:
    if not _MEETING_ID_RE.match(payload.meeting_id):
        raise HTTPException(status_code=422, detail="회의 ID는 숫자 10자리여야 합니다")

    request_tenant = (payload.tenant_address or "").strip()
    if request_tenant and any(c in request_tenant for c in _TENANT_ADDRESS_FORBIDDEN_CHARS):
        raise HTTPException(
            status_code=422, detail="tenant_address must not contain quotes or newline characters"
        )

    registry: DeviceRegistry = request.app.state.registry
    device = registry.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    tenant = request_tenant or device.teams_tenant_address or request.app.state.settings.teams_tenant_address
    if not tenant:
        raise HTTPException(status_code=422, detail="Teams 테넌트 주소가 설정되지 않았습니다")

    address = f"{payload.meeting_id}@{tenant}"
    history: ControlHistory = request.app.state.history

    try:
        async def guarded(driver):
            await reject_if_in_call(driver)
            return await driver.dial(address)

        ok = await _get_scheduler(request).run_with_driver(device_id, guarded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="device not found") from exc
    except DriverConflictError as exc:
        history.log(device_id=device_id, device_name=device.name, action="direct_dial", success=False, detail=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DriverError as exc:
        history.log(device_id=device_id, device_name=device.name, action="direct_dial", success=False, detail=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history.log(device_id=device_id, device_name=device.name, action="direct_dial", success=ok, detail=address)
    return {"ok": ok, "address": address}
