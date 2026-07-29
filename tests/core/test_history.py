import sqlite3

import pytest

from app.core.history import ControlHistory, SCHEMA_VERSION


@pytest.fixture
def history(tmp_path):
    return ControlHistory(tmp_path / "history.sqlite3")


def test_log_and_list_recent(history):
    history.log(device_id="dev-1", device_name="3층 대회의실", action="mute", success=True)
    entries = history.list_recent()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.device_id == "dev-1"
    assert entry.device_name == "3층 대회의실"
    assert entry.action == "mute"
    assert entry.success is True
    assert entry.detail is None
    assert entry.created_at


def test_log_failure_with_detail(history):
    history.log(device_id="dev-1", device_name="x", action="reboot", success=False, detail="timeout")
    entry = history.list_recent()[0]
    assert entry.success is False
    assert entry.detail == "timeout"


def test_list_recent_orders_newest_first(history):
    history.log(device_id="dev-1", device_name="x", action="mute", success=True)
    history.log(device_id="dev-1", device_name="x", action="hangup", success=True)
    history.log(device_id="dev-1", device_name="x", action="reboot", success=True)
    entries = history.list_recent()
    assert [e.action for e in entries] == ["reboot", "hangup", "mute"]


def test_list_recent_respects_limit(history):
    for i in range(5):
        history.log(device_id="dev-1", device_name="x", action=f"action-{i}", success=True)
    entries = history.list_recent(limit=2)
    assert len(entries) == 2
    assert entries[0].action == "action-4"


def test_list_recent_filters_by_device_id(history):
    history.log(device_id="dev-1", device_name="x", action="mute", success=True)
    history.log(device_id="dev-2", device_name="y", action="mute", success=True)
    entries = history.list_recent(device_id="dev-2")
    assert len(entries) == 1
    assert entries[0].device_id == "dev-2"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "history.sqlite3"
    ControlHistory(path).log(device_id="dev-1", device_name="x", action="mute", success=True)
    reopened = ControlHistory(path)
    assert len(reopened.list_recent()) == 1


def test_fresh_db_gets_current_schema_version(tmp_path):
    path = tmp_path / "history.sqlite3"
    ControlHistory(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_future_schema_version_raises(tmp_path):
    path = tmp_path / "history.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(ValueError):
        ControlHistory(path)
