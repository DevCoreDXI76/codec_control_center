import json

from fastapi.testclient import TestClient

from app.core.driver_factory import build_driver_factory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault
from app.main import app


def _client(tmp_path):
    app.state.registry = DeviceRegistry(tmp_path / "devices.enc.json")
    app.state.vault = CredentialVault(tmp_path / "credentials.enc.json")
    app.state.scheduler = PollingScheduler(
        driver_factory=build_driver_factory(app.state.registry, app.state.vault)
    )
    return TestClient(app)


def test_dashboard_empty_state(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "등록된 장비가 없습니다" in resp.text


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
