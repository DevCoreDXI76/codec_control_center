# app/core/driver_factory.py
"""
DeviceRegistry의 Device 정보 + CredentialVault의 자격증명으로
실제 DeviceDriver(Poly/Cisco) 인스턴스를 만드는 팩토리 (PollingScheduler가 사용).
"""
from __future__ import annotations

import json

from app.core.driver_base import DeviceDriver
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault
from app.drivers.cisco.cisco_driver import CiscoDriver
from app.drivers.poly.poly_driver import PolyDriver


def build_driver_factory(registry: DeviceRegistry, vault: CredentialVault):
    def factory(device_id: str) -> DeviceDriver:
        device = registry.get_device(device_id)
        if device is None:
            raise KeyError(f"unknown device id: {device_id}")

        credentials = json.loads(vault.load(device.credential_ref))
        username = credentials.get("username", "")
        password = credentials.get("password", "")

        if device.vendor == "poly":
            # PolyDriver(telnetlib3)는 현재 인증 절차를 구현하지 않는다 (Phase① 시뮬레이터 기준).
            return PolyDriver(host=device.host, port=device.port)
        if device.vendor == "cisco":
            return CiscoDriver(host=device.host, port=device.port, username=username, password=password)
        raise ValueError(f"unsupported vendor: {device.vendor}")

    return factory
