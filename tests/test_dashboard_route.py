import json

from fastapi.testclient import TestClient

from app.core.driver_factory import build_driver_factory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.settings import SettingsStore
from app.core.vault import CredentialVault
from app.main import app


def _client(tmp_path):
    app.state.registry = DeviceRegistry(tmp_path / "devices.enc.json")
    app.state.vault = CredentialVault(tmp_path / "credentials.enc.json")
    # dashboard() now reads app.state.settings (Fix 3b tenant-address prefill) — isolate it
    # the same way tests/api/test_routes_settings.py does, so this module never depends on
    # (or mutates) the real, gitignored data/settings.json on the dev machine.
    app.state.settings_store = SettingsStore(tmp_path / "settings.json")
    app.state.settings = app.state.settings_store.load()
    app.state.scheduler = PollingScheduler(
        driver_factory=build_driver_factory(app.state.registry, app.state.vault)
    )
    return TestClient(app)


def test_dashboard_empty_state(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "등록된 장비가 없습니다" in resp.text
    assert 'id="meetings-list"' not in resp.text  # 장비 없으면 회의 위젯도 숨김


def test_dashboard_renders_device_card(tmp_path):
    client = _client(tmp_path)
    credential_ref = app.state.vault.store(json.dumps({"username": "admin", "password": "pw"}))
    device = app.state.registry.add_device(
        name="3층 대회의실",
        vendor="poly",
        connection_type="telnet",
        host="127.0.0.1",
        port=2323,
        group="3F",
        credential_ref=credential_ref,
        is_simulated=True,
    )
    resp = client.get("/")
    assert resp.status_code == 200
    assert "3층 대회의실" in resp.text
    assert f'data-device-id="{device.id}"' in resp.text
    assert "SIM" in resp.text
    assert 'id="meetings-list"' in resp.text
    assert "오늘의 예정 회의" in resp.text
    assert 'id="group-tabs"' in resp.text
    assert 'data-group="3F"' in resp.text
    assert '>3F<' in resp.text
    assert 'id="alert-banner"' in resp.text
    assert "display:none" in resp.text  # 오프라인 없으니 배너는 숨김 상태로 렌더


def test_dashboard_shows_alert_banner_when_offline(tmp_path):
    import asyncio

    from app.core.driver_base import DeviceStatus

    client = _client(tmp_path)
    credential_ref = app.state.vault.store(json.dumps({"username": "admin", "password": "pw"}))
    device = app.state.registry.add_device(
        name="오프라인 장비",
        vendor="poly",
        connection_type="telnet",
        host="127.0.0.1",
        port=1,
        group="3F",
        credential_ref=credential_ref,
        is_simulated=True,
    )
    asyncio.run(app.state.scheduler.add_device(device.id))
    app.state.scheduler._runtimes[device.id].last_status = DeviceStatus(
        online=False, in_call=False, muted=False, call_peer=None, last_polled_at="now", error="offline"
    )
    resp = client.get("/")
    assert resp.status_code == 200
    assert "응답 없는 장비 1개" in resp.text
