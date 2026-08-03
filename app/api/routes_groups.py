# app/api/routes_groups.py
"""그룹(장비의 group 태그) 관리 API. 별도 그룹 엔티티가 없어 Device.group 문자열을
일괄로 조회/변경/제거한다(app/core/registry.py의 rename_group/clear_group 참고)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.registry import DeviceRegistry

router = APIRouter(prefix="/api/groups", tags=["groups"])


class GroupResponse(BaseModel):
    name: str
    device_count: int


class GroupRenameRequest(BaseModel):
    new_name: str


def _get_registry(request: Request) -> DeviceRegistry:
    return request.app.state.registry


@router.get("", response_model=list[GroupResponse])
async def list_groups(request: Request) -> list[GroupResponse]:
    devices = _get_registry(request).list_devices()
    counts: dict[str, int] = {}
    for device in devices:
        if device.group:
            counts[device.group] = counts.get(device.group, 0) + 1
    return [GroupResponse(name=name, device_count=count) for name, count in sorted(counts.items())]


@router.patch("/{name:path}")
async def rename_group(name: str, payload: GroupRenameRequest, request: Request) -> dict:
    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name must not be empty")
    registry = _get_registry(request)
    try:
        count = registry.rename_group(name, new_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"device_count": count}


@router.delete("/{name:path}")
async def delete_group(name: str, request: Request) -> dict:
    registry = _get_registry(request)
    try:
        count = registry.clear_group(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"device_count": count}
