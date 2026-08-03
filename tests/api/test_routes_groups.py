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


def _add_device(name, group):
    return app.state.registry.add_device(
        name=name,
        vendor="poly",
        connection_type="telnet",
        host="127.0.0.1",
        port=2323,
        group=group,
        credential_ref="cred-ref-1",
        is_simulated=True,
    )


def test_list_groups_empty(client):
    resp = client.get("/api/groups")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_groups_counts_devices(client):
    _add_device("A", "3F")
    _add_device("B", "3F")
    _add_device("C", "5F")
    resp = client.get("/api/groups")
    assert resp.status_code == 200
    assert resp.json() == [
        {"name": "3F", "device_count": 2},
        {"name": "5F", "device_count": 1},
    ]


def test_list_groups_ignores_ungrouped_devices(client):
    _add_device("A", "")
    resp = client.get("/api/groups")
    assert resp.json() == []


def test_rename_group_success(client):
    _add_device("A", "3F")
    resp = client.patch("/api/groups/3F", json={"new_name": "3층"})
    assert resp.status_code == 200
    assert resp.json() == {"device_count": 1}
    assert client.get("/api/groups").json() == [{"name": "3층", "device_count": 1}]


def test_rename_group_conflict_returns_409(client):
    _add_device("A", "3F")
    _add_device("B", "5F")
    resp = client.patch("/api/groups/3F", json={"new_name": "5F"})
    assert resp.status_code == 409


def test_rename_group_unknown_returns_404(client):
    resp = client.patch("/api/groups/no-such-group", json={"new_name": "x"})
    assert resp.status_code == 404


def test_delete_group_removes_tag_but_keeps_device(client):
    _add_device("A", "3F")
    resp = client.delete("/api/groups/3F")
    assert resp.status_code == 200
    assert resp.json() == {"device_count": 1}
    devices = client.get("/api/devices").json()
    assert len(devices) == 1
    assert devices[0]["group"] == ""


def test_delete_group_unknown_returns_404(client):
    resp = client.delete("/api/groups/no-such-group")
    assert resp.status_code == 404


def test_rename_group_with_slash_in_name(client):
    _add_device("A", "3F/A동")
    resp = client.patch("/api/groups/3F/A동", json={"new_name": "3층A"})
    assert resp.status_code == 200
    assert resp.json() == {"device_count": 1}
    assert client.get("/api/groups").json() == [{"name": "3층A", "device_count": 1}]


def test_delete_group_with_slash_in_name(client):
    _add_device("A", "3F/A동")
    resp = client.delete("/api/groups/3F/A동")
    assert resp.status_code == 200
    assert resp.json() == {"device_count": 1}
    devices = client.get("/api/devices").json()
    assert devices[0]["group"] == ""


def test_rename_group_empty_name_returns_400(client):
    _add_device("A", "3F")
    resp = client.patch("/api/groups/3F", json={"new_name": ""})
    assert resp.status_code == 400
    # group must be untouched
    assert client.get("/api/groups").json() == [{"name": "3F", "device_count": 1}]


def test_rename_group_whitespace_only_name_returns_400(client):
    _add_device("A", "3F")
    resp = client.patch("/api/groups/3F", json={"new_name": "   "})
    assert resp.status_code == 400
    assert client.get("/api/groups").json() == [{"name": "3F", "device_count": 1}]


def test_rename_group_trims_whitespace(client):
    _add_device("A", "3F")
    resp = client.patch("/api/groups/3F", json={"new_name": "  실제이름  "})
    assert resp.status_code == 200
    assert client.get("/api/groups").json() == [{"name": "실제이름", "device_count": 1}]
