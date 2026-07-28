# app/api/routes_devices.py
"""장비 CRUD REST API (SPEC.md 7절)."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault
from app.models.device import Device

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceCreateRequest(BaseModel):
    name: str
    vendor: str
    connection_type: str
    host: str
    port: int
    group: str
    username: str
    password: str
    is_simulated: bool = False


class DeviceUpdateRequest(BaseModel):
    name: str | None = None
    vendor: str | None = None
    connection_type: str | None = None
    host: str | None = None
    port: int | None = None
    group: str | None = None
    username: str | None = None
    password: str | None = None
    is_simulated: bool | None = None


class DeviceResponse(BaseModel):
    id: str
    name: str
    vendor: str
    connection_type: str
    host: str
    port: int
    group: str
    is_simulated: bool


def _to_response(device: Device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        vendor=device.vendor,
        connection_type=device.connection_type,
        host=device.host,
        port=device.port,
        group=device.group,
        is_simulated=device.is_simulated,
    )


def _get_registry(request: Request) -> DeviceRegistry:
    return request.app.state.registry


def _get_vault(request: Request) -> CredentialVault:
    return request.app.state.vault


@router.get("", response_model=list[DeviceResponse])
async def list_devices(request: Request) -> list[DeviceResponse]:
    registry = _get_registry(request)
    return [_to_response(d) for d in registry.list_devices()]


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, request: Request) -> DeviceResponse:
    device = _get_registry(request).get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    return _to_response(device)


@router.post("", response_model=DeviceResponse, status_code=201)
async def create_device(payload: DeviceCreateRequest, request: Request) -> DeviceResponse:
    registry = _get_registry(request)
    vault = _get_vault(request)
    credential_ref = vault.store(json.dumps({"username": payload.username, "password": payload.password}))
    try:
        device = registry.add_device(
            name=payload.name,
            vendor=payload.vendor,
            connection_type=payload.connection_type,
            host=payload.host,
            port=payload.port,
            group=payload.group,
            credential_ref=credential_ref,
            is_simulated=payload.is_simulated,
        )
    except ValueError as exc:
        vault.delete(credential_ref)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(device)


@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(device_id: str, payload: DeviceUpdateRequest, request: Request) -> DeviceResponse:
    registry = _get_registry(request)
    vault = _get_vault(request)
    existing = registry.get_device(device_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="device not found")

    changes = payload.model_dump(exclude_unset=True, exclude={"username", "password"})

    if payload.username is not None or payload.password is not None:
        current = json.loads(vault.load(existing.credential_ref))
        new_username = payload.username if payload.username is not None else current["username"]
        new_password = payload.password if payload.password is not None else current["password"]
        old_credential_ref = existing.credential_ref
        changes["credential_ref"] = vault.store(json.dumps({"username": new_username, "password": new_password}))

    try:
        device = registry.update_device(device_id, **changes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if "credential_ref" in changes:
        vault.delete(old_credential_ref)
    return _to_response(device)


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: str, request: Request) -> None:
    registry = _get_registry(request)
    vault = _get_vault(request)
    device = registry.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    registry.delete_device(device_id)
    vault.delete(device.credential_ref)
