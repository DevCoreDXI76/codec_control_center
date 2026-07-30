import pytest
from fastapi.testclient import TestClient

from app.core.driver_factory import build_driver_factory
from app.core.polling import PollingScheduler
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault
from app.main import app


@pytest.fixture
def client(tmp_path):
    app.state.registry = DeviceRegistry(tmp_path / "devices.enc.json")
    app.state.vault = CredentialVault(tmp_path / "credentials.enc.json")
    app.state.scheduler = PollingScheduler(
        driver_factory=build_driver_factory(app.state.registry, app.state.vault)
    )
    return TestClient(app)


def _create_payload(**overrides):
    payload = dict(
        name="3층 대회의실",
        vendor="poly",
        connection_type="telnet",
        host="127.0.0.1",
        port=2323,
        group="3F",
        username="admin",
        password="s3cret",
        is_simulated=True,
    )
    payload.update(overrides)
    return payload


def test_list_devices_empty(client):
    resp = client.get("/api/devices")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_device(client):
    resp = client.post("/api/devices", json=_create_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "3층 대회의실"
    assert "username" not in body
    assert "password" not in body
    assert "credential_ref" not in body


def test_create_device_persists_credentials_in_vault_not_registry(client, tmp_path):
    client.post("/api/devices", json=_create_payload())
    registry_raw = (tmp_path / "devices.enc.json").read_bytes()
    assert b"s3cret" not in registry_raw


def test_create_device_invalid_vendor_returns_422(client):
    resp = client.post("/api/devices", json=_create_payload(vendor="yealink"))
    assert resp.status_code == 422


def test_get_device_by_id(client):
    created = client.post("/api/devices", json=_create_payload()).json()
    resp = client.get(f"/api/devices/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_device_not_found(client):
    resp = client.get("/api/devices/no-such-id")
    assert resp.status_code == 404


def test_list_devices_after_create(client):
    client.post("/api/devices", json=_create_payload())
    client.post("/api/devices", json=_create_payload(name="5층 소회의실"))
    resp = client.get("/api/devices")
    assert len(resp.json()) == 2


def test_update_device_fields(client):
    created = client.post("/api/devices", json=_create_payload()).json()
    resp = client.put(f"/api/devices/{created['id']}", json={"name": "본사 임원실", "port": 2324})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "본사 임원실"
    assert body["port"] == 2324
    assert body["host"] == "127.0.0.1"  # 지정 안 한 필드는 유지


def test_update_device_credentials_replaces_vault_entry(client, tmp_path):
    created = client.post("/api/devices", json=_create_payload()).json()
    resp = client.put(f"/api/devices/{created['id']}", json={"password": "new-password"})
    assert resp.status_code == 200

    vault = app.state.vault
    registry = app.state.registry
    device = registry.get_device(created["id"])
    import json as _json

    stored = _json.loads(vault.load(device.credential_ref))
    assert stored["password"] == "new-password"
    assert stored["username"] == "admin"  # 지정 안 한 필드는 유지


def test_update_device_not_found(client):
    resp = client.put("/api/devices/no-such-id", json={"name": "x"})
    assert resp.status_code == 404


def test_delete_device(client):
    created = client.post("/api/devices", json=_create_payload()).json()
    resp = client.delete(f"/api/devices/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/devices/{created['id']}").status_code == 404


def test_delete_device_removes_credential_from_vault(client):
    created = client.post("/api/devices", json=_create_payload()).json()
    device = app.state.registry.get_device(created["id"])
    credential_ref = device.credential_ref
    client.delete(f"/api/devices/{created['id']}")
    with pytest.raises(KeyError):
        app.state.vault.load(credential_ref)


def test_delete_device_not_found(client):
    resp = client.delete("/api/devices/no-such-id")
    assert resp.status_code == 404


def test_create_device_with_teams_tenant_address(client):
    resp = client.post(
        "/api/devices",
        json={
            "name": "3층 대회의실", "vendor": "poly", "connection_type": "telnet",
            "host": "127.0.0.1", "port": 2323, "group": "3F",
            "username": "admin", "password": "pw", "is_simulated": True,
            "teams_tenant_address": "vc.poscodx.com",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["teams_tenant_address"] == "vc.poscodx.com"
    assert body["model"] is None


def test_device_response_omits_model_from_create_request_but_reflects_registry_value(client):
    resp = client.post(
        "/api/devices",
        json={
            "name": "5층 소회의실", "vendor": "cisco", "connection_type": "ssh",
            "host": "127.0.0.1", "port": 22, "group": "5F",
            "username": "admin", "password": "pw", "is_simulated": True,
        },
    )
    device_id = resp.json()["id"]
    app.state.registry.update_device(device_id, model="Room Kit Pro")
    resp2 = client.get(f"/api/devices/{device_id}")
    assert resp2.json()["model"] == "Room Kit Pro"
