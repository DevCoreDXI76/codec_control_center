import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.core.driver_base import CalendarEntry, DeviceDriver, DeviceStatus
from app.core.driver_factory import build_driver_factory
from app.core.history import ControlHistory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault
from app.main import app
from app.simulator.cisco_sim_server import CiscoSimServer

# CiscoSimServer는 paramiko(동기) 기반으로 자체 스레드에서 돌기 때문에
# FastAPI TestClient(별도 스레드/이벤트루프)에서 접속해도 루프 충돌이 없다.
# (asyncio 기반 PolySimServer는 자신을 띄운 이벤트루프에 묶여 TestClient와 루프가
#  달라지면 응답을 못 받는 문제가 있어 이 통합 테스트에서는 사용하지 않는다.)


@pytest.fixture
def cisco_sim():
    sim = CiscoSimServer(host="127.0.0.1", port=0)
    sim.start()
    yield sim
    sim.stop()


@pytest.fixture
def client(tmp_path):
    app.state.registry = DeviceRegistry(tmp_path / "devices.enc.json")
    app.state.vault = CredentialVault(tmp_path / "credentials.enc.json")
    app.state.scheduler = PollingScheduler(
        driver_factory=build_driver_factory(app.state.registry, app.state.vault)
    )
    app.state.history = ControlHistory(tmp_path / "history.sqlite3")
    return TestClient(app)


def _register_cisco_device(cisco_sim) -> str:
    credential_ref = app.state.vault.store(json.dumps({"username": "admin", "password": "pw"}))
    device = app.state.registry.add_device(
        name="시뮬레이터 회의실",
        vendor="cisco",
        connection_type="ssh",
        host="127.0.0.1",
        port=cisco_sim.port,
        group="TEST",
        credential_ref=credential_ref,
        is_simulated=True,
    )
    asyncio.run(app.state.scheduler.add_device(device.id))
    return device.id


def test_get_status_unknown_device_404(client):
    resp = client.get("/api/devices/no-such-id/status")
    assert resp.status_code == 404


def test_get_status_against_simulator(client, cisco_sim):
    device_id = _register_cisco_device(cisco_sim)
    resp = client.get(f"/api/devices/{device_id}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["in_call"] is False


def test_mute_reflected_in_simulator_state(client, cisco_sim):
    device_id = _register_cisco_device(cisco_sim)
    resp = client.post(f"/api/devices/{device_id}/mute", json={"on": True})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert cisco_sim.state.muted is True

    resp = client.post(f"/api/devices/{device_id}/mute", json={"on": False})
    assert resp.json() == {"ok": True}
    assert cisco_sim.state.muted is False


def test_mute_logs_to_history(client, cisco_sim):
    device_id = _register_cisco_device(cisco_sim)
    client.post(f"/api/devices/{device_id}/mute", json={"on": True})
    entries = app.state.history.list_recent()
    assert len(entries) == 1
    assert entries[0].action == "mute"
    assert entries[0].success is True
    assert entries[0].device_id == device_id


def test_failed_control_logs_failure_to_history(client):
    resp = client.post("/api/devices/no-such-id/mute", json={"on": True})
    assert resp.status_code == 404
    # 장비 자체를 못 찾은 경우(404)는 이력에 남기지 않는다 (실행된 명령이 없으므로)
    assert app.state.history.list_recent() == []


def test_dial_and_hangup(client, cisco_sim):
    device_id = _register_cisco_device(cisco_sim)
    resp = client.post(f"/api/devices/{device_id}/dial", json={"address": "1234@example.com"})
    assert resp.status_code == 200
    assert cisco_sim.state.in_call is True

    resp = client.post(f"/api/devices/{device_id}/hangup")
    assert resp.status_code == 200
    assert cisco_sim.state.in_call is False


def test_reboot(client, cisco_sim):
    device_id = _register_cisco_device(cisco_sim)
    resp = client.post(f"/api/devices/{device_id}/reboot")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_mute_unknown_device_404(client):
    resp = client.post("/api/devices/no-such-id/mute", json={"on": True})
    assert resp.status_code == 404


class _InCallAwareDriver(DeviceDriver):
    """get_status()의 in_call을 자유롭게 설정해 가드 로직만 독립적으로 검증하기 위한 가짜 드라이버."""

    def __init__(self, in_call: bool = False, online: bool = True) -> None:
        self.in_call = in_call
        self.online = online
        self.reboot_called = False
        self.dialed_address: str | None = None

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_status(self) -> DeviceStatus:
        return DeviceStatus(online=self.online, in_call=self.in_call, muted=False, call_peer=None, last_polled_at="now")

    async def mute(self, on: bool) -> bool:
        return True

    async def dial(self, address: str) -> bool:
        self.dialed_address = address
        return True

    async def hangup(self) -> bool:
        return True

    async def reboot(self) -> bool:
        self.reboot_called = True
        return True

    async def get_calendar_status(self) -> str:
        return "registered"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        return []

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        return True


def _register_device_with_driver(driver: DeviceDriver) -> str:
    credential_ref = app.state.vault.store(json.dumps({"username": "admin", "password": "pw"}))
    device = app.state.registry.add_device(
        name="통화중장비",
        vendor="cisco",
        connection_type="ssh",
        host="127.0.0.1",
        port=1,
        group="TEST",
        credential_ref=credential_ref,
        is_simulated=True,
    )
    app.state.scheduler = PollingScheduler(driver_factory=lambda device_id: driver)
    asyncio.run(app.state.scheduler.add_device(device.id))
    return device.id


class _BoomDriver(DeviceDriver):
    """DriverError가 아닌 예상 밖 예외(버그)를 흉내내는 테스트 전용 드라이버."""

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_status(self) -> DeviceStatus:
        return DeviceStatus(online=True, in_call=False, muted=False, call_peer=None, last_polled_at="now")

    async def mute(self, on: bool) -> bool:
        raise RuntimeError("boom")

    async def dial(self, address: str) -> bool:
        raise RuntimeError("boom")

    async def hangup(self) -> bool:
        raise RuntimeError("boom")

    async def reboot(self) -> bool:
        raise RuntimeError("boom")

    async def get_calendar_status(self) -> str:
        return "registered"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        return []

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        raise RuntimeError("boom")


def test_unexpected_driver_exception_returns_502_and_logs_history(client):
    credential_ref = app.state.vault.store(json.dumps({"username": "admin", "password": "pw"}))
    device = app.state.registry.add_device(
        name="버그있는장비",
        vendor="cisco",
        connection_type="ssh",
        host="127.0.0.1",
        port=1,
        group="TEST",
        credential_ref=credential_ref,
        is_simulated=True,
    )
    app.state.scheduler = PollingScheduler(driver_factory=lambda device_id: _BoomDriver())
    asyncio.run(app.state.scheduler.add_device(device.id))

    resp = client.post(f"/api/devices/{device.id}/mute", json={"on": True})
    assert resp.status_code == 502
    assert "unexpected error" in resp.json()["detail"]

    entries = app.state.history.list_recent()
    assert len(entries) == 1
    assert entries[0].success is False
    assert entries[0].action == "mute"


def test_reboot_blocked_when_in_call(client):
    driver = _InCallAwareDriver(in_call=True)
    device_id = _register_device_with_driver(driver)

    resp = client.post(f"/api/devices/{device_id}/reboot")

    assert resp.status_code == 409
    assert "이미 통화 중" in resp.json()["detail"]
    assert driver.reboot_called is False
    entries = app.state.history.list_recent()
    assert len(entries) == 1
    assert entries[0].action == "reboot"
    assert entries[0].success is False


def test_dial_blocked_when_in_call(client):
    driver = _InCallAwareDriver(in_call=True)
    device_id = _register_device_with_driver(driver)

    resp = client.post(f"/api/devices/{device_id}/dial", json={"address": "1234@example.com"})

    assert resp.status_code == 409
    assert "이미 통화 중" in resp.json()["detail"]
    assert driver.dialed_address is None
    entries = app.state.history.list_recent()
    assert len(entries) == 1
    assert entries[0].action == "dial"
    assert entries[0].success is False


def test_reboot_blocked_when_status_unreadable(client):
    driver = _InCallAwareDriver(online=False, in_call=False)
    device_id = _register_device_with_driver(driver)

    resp = client.post(f"/api/devices/{device_id}/reboot")

    assert resp.status_code == 409
    assert driver.reboot_called is False


def test_dial_blocked_when_status_unreadable(client):
    driver = _InCallAwareDriver(online=False, in_call=False)
    device_id = _register_device_with_driver(driver)

    resp = client.post(f"/api/devices/{device_id}/dial", json={"address": "1234@example.com"})

    assert resp.status_code == 409
    assert driver.dialed_address is None
