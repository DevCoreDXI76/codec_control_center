import pytest
from fastapi.testclient import TestClient

from app.core.driver_factory import build_driver_factory
from app.core.history import ControlHistory
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
    app.state.history = ControlHistory(tmp_path / "history.sqlite3")
    app.state.app_log_path = tmp_path / "app.log"
    return TestClient(app)


def test_list_logs_empty(client):
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_logs_returns_entries(client):
    app.state.history.log(device_id="dev-1", device_name="3층 대회의실", action="mute", success=True)
    app.state.history.log(device_id="dev-2", device_name="5층 임원실", action="reboot", success=False, detail="timeout")

    resp = client.get("/api/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["action"] == "reboot"  # 최신순
    assert body[0]["success"] is False
    assert body[0]["detail"] == "timeout"


def test_list_logs_filters_by_device_id(client):
    app.state.history.log(device_id="dev-1", device_name="x", action="mute", success=True)
    app.state.history.log(device_id="dev-2", device_name="y", action="mute", success=True)

    resp = client.get("/api/logs", params={"device_id": "dev-2"})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["device_id"] == "dev-2"


def test_logs_page_renders_empty_state(client):
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "아직 기록된 제어 이력이 없습니다" in resp.text


def test_logs_page_renders_entries(client):
    app.state.history.log(device_id="dev-1", device_name="3층 대회의실", action="mute", success=True)
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "3층 대회의실" in resp.text
    assert "mute" in resp.text
    assert "성공" in resp.text


def test_system_log_page_renders_empty_state(client):
    resp = client.get("/logs/system")
    assert resp.status_code == 200
    assert "아직 기록된 시스템 로그가 없습니다" in resp.text


def test_system_log_page_renders_lines_newest_first(client):
    app.state.app_log_path.write_text(
        "2026-07-30 10:00:00 INFO app: first\n2026-07-30 10:00:01 WARNING app: second\n",
        encoding="utf-8",
    )
    resp = client.get("/logs/system")
    assert resp.status_code == 200
    assert resp.text.index("second") < resp.text.index("first")  # 최신 줄이 위로


def test_logs_page_shows_control_tab_active(client):
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert '<a href="/logs" class="active">제어 로그</a>' in resp.text
    assert '<a href="/logs/system" class="">시스템 로그</a>' in resp.text


def test_system_log_page_shows_system_tab_active(client):
    resp = client.get("/logs/system")
    assert resp.status_code == 200
    assert '<a href="/logs" class="">제어 로그</a>' in resp.text
    assert '<a href="/logs/system" class="active">시스템 로그</a>' in resp.text
