import asyncio
import json

import pytest
from fastapi.testclient import TestClient

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
