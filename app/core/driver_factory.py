# app/core/driver_factory.py
"""
DeviceRegistry의 Device 정보 + CredentialVault의 자격증명으로
실제 DeviceDriver(Poly/Cisco) 인스턴스를 만드는 팩토리 (PollingScheduler가 사용).
"""
from __future__ import annotations

import json
from collections.abc import Callable

from app.core.driver_base import DeviceDriver
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault
from app.drivers.cisco.cisco_driver import CiscoDriver
from app.drivers.poly.poly_driver import PolyDriver


def build_driver_factory(
    registry: DeviceRegistry,
    vault: CredentialVault,
    get_timeout: Callable[[], float] = lambda: 7.0,
):
    """get_timeout은 드라이버 생성 시점마다 호출된다 — 설정 화면에서 명령
    타임아웃을 바꾸면 다음번 (재)연결부터 새 값이 반영되도록 하기 위함."""

    def factory(device_id: str) -> DeviceDriver:
        device = registry.get_device(device_id)
        if device is None:
            raise KeyError(f"unknown device id: {device_id}")

        credentials = json.loads(vault.load(device.credential_ref))
        username = credentials.get("username", "")
        password = credentials.get("password", "")
        timeout = get_timeout()

        if device.vendor == "poly":
            # connection_type="ssh"면 paramiko(ID/PW 인증), "telnet"이면 telnetlib3(무인증)로 접속한다.
            return PolyDriver(
                host=device.host,
                port=device.port,
                timeout=timeout,
                transport=device.connection_type,
                username=username,
                password=password,
            )
        if device.vendor == "cisco":
            return CiscoDriver(
                host=device.host, port=device.port, username=username, password=password, timeout=timeout
            )
        raise ValueError(f"unsupported vendor: {device.vendor}")

    return factory
