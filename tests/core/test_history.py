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


def test_created_at_displayed_in_kst_not_utc(history, tmp_path):
    """제어 로그 시각이 DB에는 UTC로 저장되지만 화면에는 KST(UTC+9)로 표시돼야 한다
    (2026-07-31 VDI 2차 재테스트 — UTC 그대로 노출돼 실제 한국 시간과 9시간 어긋나 보이던 문제)."""
    conn = sqlite3.connect(history.db_path)
    conn.execute(
        "INSERT INTO control_log (device_id, device_name, action, success, detail, created_at) "
        "VALUES ('dev-1', 'x', 'mute', 1, NULL, '2026-07-31T07:14:14+00:00')"
    )
    conn.commit()
    conn.close()

    entry = history.list_recent()[0]
    assert entry.created_at == "2026-07-31 16:14:14"


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
