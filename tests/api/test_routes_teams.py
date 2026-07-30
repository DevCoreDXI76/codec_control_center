import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.driver_base import (
    CalendarEntry,
    DeviceDriver,
    DeviceStatus,
)
from app.core.history import ControlHistory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.settings import AppSettings, SettingsStore
from app.core.vault import CredentialVault
from app.main import app

# 라우트 계층(파라미터 전달/에러 매핑)만 검증하므로 실제 Poly 프로토콜이 아닌
# 제어 가능한 가짜 드라이버를 사용한다 (프로토콜 자체는 test_poly_driver.py에서 검증됨).


class FakeTeamsDriver(DeviceDriver):
    def __init__(self, calendar_supported: bool = True) -> None:
        self.calendar_supported = calendar_supported
        self.joined_entry: CalendarEntry | None = None
        self.dialed_address: str | None = None

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_status(self) -> DeviceStatus:
        return DeviceStatus(online=True, in_call=False, muted=False, call_peer=None, last_polled_at="now")

    async def mute(self, on: bool) -> bool:
        return True

    async def dial(self, address: str) -> bool:
        self.dialed_address = address
        return True

    async def hangup(self) -> bool:
        return True

    async def reboot(self) -> bool:
        return True

    async def get_calendar_status(self) -> str:
        if not self.calendar_supported:
            raise NotImplementedError("calendar not supported")
        return "registered"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        if not self.calendar_supported:
            raise NotImplementedError("obtp not supported")
        return [
            CalendarEntry(
                subject="주간 전체회의",
                start_time="2026-07-29T14:00:00",
                end_time="2026-07-29T15:00:00",
                join_uri="sip:weekly@example.com",
            )
        ]

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        if not entry.join_uri:
            from app.core.driver_base import DriverCommandError

            raise DriverCommandError("meeting has no dialable join_uri")
        self.joined_entry = entry
        return True


@pytest.fixture
def client(tmp_path):
    app.state.registry = DeviceRegistry(tmp_path / "devices.enc.json")
    app.state.vault = CredentialVault(tmp_path / "credentials.enc.json")
    app.state.history = ControlHistory(tmp_path / "history.sqlite3")
    # settings_store must be redirected to tmp_path too — tests in this module save/reload
    # AppSettings (see test_direct_dial_falls_back_to_global_tenant), and without this the
    # real, gitignored data/settings.json on the dev machine gets overwritten as a side
    # effect (mirrors tests/api/test_routes_settings.py's isolation pattern).
    app.state.settings_store = SettingsStore(tmp_path / "settings.json")
    app.state.settings = app.state.settings_store.load()
    return TestClient(app)


def _register(client, calendar_supported: bool = True, teams_tenant_address: str | None = None) -> tuple[str, FakeTeamsDriver]:
    credential_ref = app.state.vault.store('{"username":"admin","password":"pw"}')
    device = app.state.registry.add_device(
        name="테스트 회의실",
        vendor="poly",
        connection_type="telnet",
        host="127.0.0.1",
        port=2323,
        group="TEST",
        credential_ref=credential_ref,
        is_simulated=True,
        teams_tenant_address=teams_tenant_address,
    )
    fake_driver = FakeTeamsDriver(calendar_supported=calendar_supported)
    app.state.scheduler = PollingScheduler(driver_factory=lambda device_id: fake_driver)
    asyncio.run(app.state.scheduler.add_device(device.id))
    return device.id, fake_driver


def test_get_calendar_supported(client):
    device_id, _driver = _register(client, calendar_supported=True)
    resp = client.get(f"/api/devices/{device_id}/calendar")
    assert resp.status_code == 200
    assert resp.json() == {"supported": True, "status": "registered"}


def test_get_calendar_not_supported(client):
    device_id, _driver = _register(client, calendar_supported=False)
    resp = client.get(f"/api/devices/{device_id}/calendar")
    assert resp.status_code == 200
    assert resp.json() == {"supported": False, "status": None}


def test_get_calendar_unknown_device_404(client):
    _register(client)
    resp = client.get("/api/devices/no-such-id/calendar")
    assert resp.status_code == 404


def test_get_obtp_supported_returns_entries(client):
    device_id, _driver = _register(client, calendar_supported=True)
    resp = client.get(f"/api/devices/{device_id}/obtp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["supported"] is True
    assert len(body["entries"]) == 1
    assert body["entries"][0]["subject"] == "주간 전체회의"
    assert body["entries"][0]["join_uri"] == "sip:weekly@example.com"


def test_get_obtp_not_supported(client):
    device_id, _driver = _register(client, calendar_supported=False)
    resp = client.get(f"/api/devices/{device_id}/obtp")
    assert resp.status_code == 200
    assert resp.json() == {"supported": False, "entries": []}


def test_join_meeting_success(client):
    device_id, driver = _register(client)
    resp = client.post(
        f"/api/devices/{device_id}/join",
        json={
            "subject": "주간 전체회의",
            "start_time": "2026-07-29T14:00:00",
            "end_time": "2026-07-29T15:00:00",
            "join_uri": "sip:weekly@example.com",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert driver.joined_entry is not None
    assert driver.joined_entry.join_uri == "sip:weekly@example.com"


def test_join_meeting_without_uri_returns_502(client):
    device_id, _driver = _register(client)
    resp = client.post(
        f"/api/devices/{device_id}/join",
        json={"subject": "미확정 회의", "start_time": "x", "end_time": "y", "join_uri": None},
    )
    assert resp.status_code == 502


def test_direct_dial_uses_device_tenant_override(client):
    device_id, driver = _register(client, teams_tenant_address="room.vc.poscodx.com")
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "address": "1234567890@room.vc.poscodx.com"}
    assert driver.dialed_address == "1234567890@room.vc.poscodx.com"


def test_direct_dial_falls_back_to_global_tenant(client):
    app.state.settings_store.save(AppSettings(teams_tenant_address="vc.poscodx.com"))
    app.state.settings = app.state.settings_store.load()
    device_id, _driver = _register(client)
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    assert resp.status_code == 200
    assert resp.json()["address"] == "1234567890@vc.poscodx.com"


def test_direct_dial_rejects_non_10_digit_meeting_id(client):
    device_id, _driver = _register(client, teams_tenant_address="vc.poscodx.com")
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "12345"})
    assert resp.status_code == 422


def test_direct_dial_rejects_meeting_id_with_trailing_newline(client):
    # Python's re `$` matches just before a trailing "\n", so a naive `^\d{10}$`
    # would accept "1234567890\n" and let a newline slip into the address that
    # gets interpolated raw into the device's command line (telnet/SSH).
    device_id, _driver = _register(client, teams_tenant_address="vc.poscodx.com")
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890\n"})
    assert resp.status_code == 422


def test_direct_dial_request_tenant_overrides_device_and_global(client):
    app.state.settings_store.save(AppSettings(teams_tenant_address="global.vc.poscodx.com"))
    app.state.settings = app.state.settings_store.load()
    device_id, driver = _register(client, teams_tenant_address="device.vc.poscodx.com")
    resp = client.post(
        f"/api/devices/{device_id}/direct-dial",
        json={"meeting_id": "1234567890", "tenant_address": "override.vc.poscodx.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["address"] == "1234567890@override.vc.poscodx.com"
    assert driver.dialed_address == "1234567890@override.vc.poscodx.com"


def test_direct_dial_blank_request_tenant_falls_back_to_device(client):
    device_id, driver = _register(client, teams_tenant_address="device.vc.poscodx.com")
    resp = client.post(
        f"/api/devices/{device_id}/direct-dial",
        json={"meeting_id": "1234567890", "tenant_address": "  "},
    )
    assert resp.status_code == 200
    assert resp.json()["address"] == "1234567890@device.vc.poscodx.com"


def test_direct_dial_omitted_request_tenant_falls_back_exactly_as_before(client):
    device_id, driver = _register(client, teams_tenant_address="room.vc.poscodx.com")
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "address": "1234567890@room.vc.poscodx.com"}


def test_direct_dial_without_any_tenant_configured_returns_422(client):
    app.state.settings = AppSettings(teams_tenant_address="")
    device_id, _driver = _register(client)
    resp = client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    assert resp.status_code == 422


def test_direct_dial_logs_to_history(client):
    device_id, _driver = _register(client, teams_tenant_address="vc.poscodx.com")
    client.post(f"/api/devices/{device_id}/direct-dial", json={"meeting_id": "1234567890"})
    entries = app.state.history.list_recent()
    assert len(entries) == 1
    assert entries[0].action == "direct_dial"
    assert entries[0].success is True
