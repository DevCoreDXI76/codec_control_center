# app/core/registry.py
"""
장비 레지스트리 저장/조회 (SPEC.md 2절/6.1절).

레지스트리 파일 전체를 DPAPI로 암호화해 devices.enc.json에 저장한다.
장비의 계정정보(ID/PW)는 여기 저장하지 않고, CredentialVault가 발급한
credential_ref(uuid)만 참조로 남긴다 — 실제 평문은 CredentialVault에서만 다룬다.
"""
from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

from app.core import dpapi
from app.models.device import Device

_ENTROPY = b"codec-control-center-registry"

SCHEMA_VERSION = 1
"""devices.enc.json 저장 형식 버전. 필드 추가/구조 변경 시 올리고,
_migrate()에 "if version < N: ..." 형태로 단계별 변환을 추가한다."""


class DeviceRegistry:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write([])

    def list_devices(self) -> list[Device]:
        return self._read()

    def get_device(self, device_id: str) -> Device | None:
        for device in self._read():
            if device.id == device_id:
                return device
        return None

    def add_device(
        self,
        *,
        name: str,
        vendor: str,
        connection_type: str,
        host: str,
        port: int,
        group: str,
        credential_ref: str,
        is_simulated: bool = False,
        teams_tenant_address: str | None = None,
    ) -> Device:
        device = Device(
            id=str(uuid.uuid4()),
            name=name,
            vendor=vendor,
            connection_type=connection_type,
            host=host,
            port=port,
            group=group,
            credential_ref=credential_ref,
            is_simulated=is_simulated,
            teams_tenant_address=teams_tenant_address,
        )
        devices = self._read()
        devices.append(device)
        self._write(devices)
        return device

    def update_device(self, device_id: str, **changes) -> Device:
        devices = self._read()
        for i, device in enumerate(devices):
            if device.id == device_id:
                updated = dataclasses.replace(device, **changes)
                devices[i] = updated
                self._write(devices)
                return updated
        raise KeyError(f"unknown device id: {device_id}")

    def delete_device(self, device_id: str) -> None:
        devices = [d for d in self._read() if d.id != device_id]
        self._write(devices)

    def rename_group(self, old_name: str, new_name: str) -> int:
        """old_name을 가진 모든 장비의 group을 new_name으로 바꾼다. 반환값은 변경된
        장비 수. old_name을 가진 장비가 없으면 KeyError(update_device의 미존재 id
        처리와 동일 패턴), new_name이 이미 다른 그룹으로 쓰이고 있으면 ValueError로
        차단한다(병합하지 않음)."""
        devices = self._read()
        matching_ids = {d.id for d in devices if d.group == old_name}
        if not matching_ids:
            raise KeyError(f"no devices found in group {old_name!r}")
        if any(d.group == new_name for d in devices if d.id not in matching_ids):
            raise ValueError(f"group {new_name!r} already exists")
        devices = [
            dataclasses.replace(d, group=new_name) if d.id in matching_ids else d
            for d in devices
        ]
        self._write(devices)
        return len(matching_ids)

    def clear_group(self, name: str) -> int:
        """name을 가진 모든 장비의 group을 ""로 비운다(장비 자체는 삭제하지 않음).
        반환값은 변경된 장비 수. name을 가진 장비가 없으면 KeyError."""
        devices = self._read()
        matching_ids = {d.id for d in devices if d.group == name}
        if not matching_ids:
            raise KeyError(f"no group named {name!r}")
        devices = [
            dataclasses.replace(d, group="") if d.id in matching_ids else d
            for d in devices
        ]
        self._write(devices)
        return len(matching_ids)

    def _read(self) -> list[Device]:
        raw = self.store_path.read_bytes()
        if not raw:
            return []
        decrypted = dpapi.unprotect(raw, _ENTROPY)
        payload = _migrate(json.loads(decrypted.decode("utf-8")))
        return [Device(**item) for item in payload.get("devices", [])]

    def _write(self, devices: list[Device]) -> None:
        payload = json.dumps(
            {"schema_version": SCHEMA_VERSION, "devices": [dataclasses.asdict(d) for d in devices]},
            ensure_ascii=False,
        ).encode("utf-8")
        encrypted = dpapi.protect(payload, _ENTROPY)
        self.store_path.write_bytes(encrypted)


def _migrate(payload: dict) -> dict:
    """구버전 devices.enc.json을 현재 스키마로 변환한다.

    schema_version 필드가 없는 파일(1.0.0 이전, 이 필드가 생기기 전)은 1로 간주한다.
    """
    version = payload.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"devices.enc.json schema_version={version}이 현재 앱이 지원하는 "
            f"최대 버전({SCHEMA_VERSION})보다 높습니다 — 더 최신 버전의 앱으로 실행해주세요."
        )
    # version == 1은 현재 스키마와 동일. 향후 스키마가 바뀌면 여기에 단계별 변환을 추가한다.
    return payload
