import asyncio

import pytest
import pytest_asyncio

from app.core.driver_base import CalendarEntry, DriverCommandError
from app.drivers.poly import poly_commands as poly_cmd
from app.drivers.poly.poly_driver import PolyDriver, _normalize_poly_datetime, _parse_uptime
from app.simulator.poly_sim_server import PolySimServer, PolySSHSimServer


@pytest_asyncio.fixture
async def sim_and_driver():
    sim = PolySimServer(host="127.0.0.1", port=0)
    await sim.start()
    port = sim._server.sockets[0].getsockname()[1]

    driver = PolyDriver(host="127.0.0.1", port=port, timeout=3.0)
    await driver.connect()
    try:
        yield sim, driver
    finally:
        await driver.disconnect()
        await sim.stop()


@pytest_asyncio.fixture
async def ssh_sim_and_driver():
    sim = PolySSHSimServer(host="127.0.0.1", port=0)
    await asyncio.to_thread(sim.start)

    driver = PolyDriver(
        host="127.0.0.1", port=sim.port, timeout=3.0, transport="ssh", username="admin", password="pw"
    )
    await driver.connect()
    try:
        yield sim, driver
    finally:
        await driver.disconnect()
        await asyncio.to_thread(sim.stop)


async def test_get_status_idle(sim_and_driver):
    _sim, driver = sim_and_driver
    status = await driver.get_status()
    assert status.online is True
    assert status.in_call is False
    assert status.muted is False
    assert status.error is None


async def test_mute_unmute_reflected_in_status(sim_and_driver):
    sim, driver = sim_and_driver
    assert await driver.mute(True) is True
    assert sim.state.muted is True
    status = await driver.get_status()
    assert status.muted is True

    assert await driver.mute(False) is True
    assert sim.state.muted is False


async def test_dial_then_status_shows_in_call(sim_and_driver):
    sim, driver = sim_and_driver
    assert await driver.dial("5551212") is True
    assert sim.state.in_call is True

    status = await driver.get_status()
    assert status.in_call is True
    assert status.call_peer == "5551212"


async def test_hangup_clears_call(sim_and_driver):
    sim, driver = sim_and_driver
    await driver.dial("5551212")
    assert await driver.hangup() is True
    assert sim.state.in_call is False

    status = await driver.get_status()
    assert status.in_call is False


# --- 2026-07-31 VDI 실장비 검증: 예상 밖 응답을 조용히 False로 삼키지 않고 원문과 함께
# DriverCommandError로 올린다(Cisco _check_result_ok와 동일한 원칙) — 예전에는 mute 실패가
# 로그에 원인 없이 "실패"로만 남아 진단이 불가능했다.


async def test_mute_raises_with_raw_response_on_mismatch():
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._call = lambda command: _async_return("some unexpected text")
    with pytest.raises(DriverCommandError, match="some unexpected text"):
        await driver.mute(True)


async def test_dial_raises_with_raw_response_on_mismatch():
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._call = lambda command: _async_return("busy")
    with pytest.raises(DriverCommandError, match="busy"):
        await driver.dial("1234")


async def test_hangup_raises_with_raw_response_on_mismatch():
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._call = lambda command: _async_return("no active call")
    with pytest.raises(DriverCommandError, match="no active call"):
        await driver.hangup()


async def _async_return(value):
    return value


async def test_model_retried_on_next_poll_if_initially_unknown():
    """connect() 시점의 모델 조회가 실패해도 "모델 확인 중..."에 영영 머무르지 않고
    다음 get_status() 폴링에서 다시 시도해야 한다 (2026-07-31 VDI 실장비 검증에서
    모델명이 계속 "확인 중"으로만 표시되던 문제)."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._model = None  # connect() 때 모델 조회가 실패했다고 가정

    async def fake_call(command):
        if command == poly_cmd.SYSTEMSETTING_GET_MODEL:
            return 'systemsetting model "Group 700"'
        if command == poly_cmd.MUTE_NEAR_GET:
            return "mute near off"
        if command == poly_cmd.UPTIME_GET:
            return "1 Hour, 0 Minutes"
        raise AssertionError(f"unexpected command in test stub: {command}")

    async def fake_call_block(command, begin, end):
        return ["system is not in a call"]

    driver._call = fake_call
    driver._call_block = fake_call_block

    status = await driver.get_status()

    assert status.model == "Group 700"
    assert driver._model == "Group 700"


async def test_model_not_refetched_once_known():
    """모델을 이미 알고 있으면 매 폴링마다 다시 조회하지 않는다(불필요한 명령 낭비 방지)."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._model = "Group 700"
    calls: list[str] = []

    async def fake_call(command):
        calls.append(command)
        if command == poly_cmd.MUTE_NEAR_GET:
            return "mute near off"
        if command == poly_cmd.UPTIME_GET:
            return "1 Hour, 0 Minutes"
        raise AssertionError(f"unexpected command in test stub: {command}")

    async def fake_call_block(command, begin, end):
        return ["system is not in a call"]

    driver._call = fake_call
    driver._call_block = fake_call_block

    await driver.get_status()

    assert poly_cmd.SYSTEMSETTING_GET_MODEL not in calls


async def test_reboot_returns_true_without_hanging(sim_and_driver):
    _sim, driver = sim_and_driver
    assert await driver.reboot() is True


async def test_get_calendar_status_registered(sim_and_driver):
    _sim, driver = sim_and_driver
    assert await driver.get_calendar_status() == "registered"


async def test_get_calendar_status_not_registered(sim_and_driver):
    sim, driver = sim_and_driver
    sim.state.calendar_established = False
    assert await driver.get_calendar_status() == "not_registered"


async def test_get_obtp_entries_returns_seeded_meeting(sim_and_driver):
    _sim, driver = sim_and_driver
    entries = await driver.get_obtp_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, CalendarEntry)
    assert entry.subject == "주간 전체회의"
    assert entry.join_uri == "sip:weekly@example.com"
    # MockMeeting 시드 데이터는 raw Poly 포맷("2026-07-28:14:00")을 쓰지만,
    # get_obtp_entries()가 Cisco(ISO 8601)와 비교 가능한 T-구분 형태로 정규화해야 한다
    # (JS 쪽 사전순 문자열 비교가 두 벤더 모두에서 정확히 동작하려면 필수 — Fix 2 참고).
    assert entry.start_time == "2026-07-28T14:00:00"
    assert entry.end_time == "2026-07-28T15:00:00"


async def test_join_meeting_dials_join_uri(sim_and_driver):
    sim, driver = sim_and_driver
    entries = await driver.get_obtp_entries()
    assert await driver.join_meeting(entries[0]) is True
    assert sim.state.in_call is True
    assert sim.state.call_peer == "sip:weekly@example.com"


async def test_full_lifecycle_no_exceptions(sim_and_driver):
    """Phase① DoD: connect/get_status/mute/dial/hangup/reboot 전부 예외 없이 동작."""
    _sim, driver = sim_and_driver
    await driver.get_status()
    await driver.mute(True)
    await driver.mute(False)
    await driver.dial("1234")
    await driver.hangup()
    await driver.reboot()


async def test_get_status_includes_model_and_uptime(sim_and_driver):
    _sim, driver = sim_and_driver
    status = await driver.get_status()
    assert status.model == "RealPresence Group 500 (SIM)"
    assert status.uptime_seconds is not None


async def test_get_status_uptime_failure_still_reports_online():
    """uptime get만 실패(무응답)해도 mute/callinfo 조회는 정상 진행되어
    online=True를 유지해야 한다 — uptime 실패가 전체 offline 판정으로
    번지지 않도록 get_status()가 uptime 조회를 개별 보호하는지 검증.
    (짧은 timeout으로 타임아웃 대기를 최소화)"""
    sim = PolySimServer(host="127.0.0.1", port=0)
    await sim.start()
    port = sim._server.sockets[0].getsockname()[1]

    driver = PolyDriver(host="127.0.0.1", port=port, timeout=0.5)
    await driver.connect()
    try:
        sim.state.uptime_fails = True
        status = await driver.get_status()
    finally:
        await driver.disconnect()
        await sim.stop()

    assert status.online is True
    assert status.error is None
    assert status.uptime_seconds is None
    assert status.model == "RealPresence Group 500 (SIM)"


def test_invalid_transport_raises_valueerror():
    with pytest.raises(ValueError):
        PolyDriver(host="127.0.0.1", transport="http")


# --- SSH 트랜스포트 (Phase③ 실장비 검증: connection_type="ssh" 장비 대응) ---
# 동일 명령 세트를 SSH로 접속해도 동작함을 확인 — 위 Telnet 테스트와 대칭.


async def test_ssh_get_status_idle(ssh_sim_and_driver):
    _sim, driver = ssh_sim_and_driver
    status = await driver.get_status()
    assert status.online is True
    assert status.error is None


async def test_ssh_mute_unmute_reflected_in_status(ssh_sim_and_driver):
    sim, driver = ssh_sim_and_driver
    assert await driver.mute(True) is True
    assert sim.state.muted is True
    status = await driver.get_status()
    assert status.muted is True


async def test_ssh_full_lifecycle_no_exceptions(ssh_sim_and_driver):
    _sim, driver = ssh_sim_and_driver
    await driver.get_status()
    await driver.mute(True)
    await driver.dial("1234")
    await driver.hangup()
    await driver.reboot()


async def test_ssh_connects_to_device_offering_only_legacy_ssh_rsa_hostkey():
    """2026-07-30 VDI 실장비 검증에서 확인된 문제의 회귀 테스트: 일부 Poly Group
    Series 실장비는 SSH 호스트키로 ssh-rsa(SHA-1)만 제시하는데, paramiko 5.x는
    기본적으로 이를 협상 목록/서명 해시 매핑 양쪽에서 빼버려 연결 자체가 실패한다
    (`Incompatible ssh peer (no acceptable host key)`). PolyDriver.connect()가
    이 제약이 있는 장비에도 정상 접속되는지 확인한다."""
    sim = PolySSHSimServer(host="127.0.0.1", port=0, restrict_to_ssh_rsa=True)
    await asyncio.to_thread(sim.start)

    driver = PolyDriver(
        host="127.0.0.1", port=sim.port, timeout=3.0, transport="ssh", username="admin", password="pw"
    )
    try:
        await driver.connect()
        status = await driver.get_status()
        assert status.online is True
    finally:
        await driver.disconnect()
        await asyncio.to_thread(sim.stop)


def test_parse_uptime_hours_and_minutes():
    assert _parse_uptime("1 Hour, 10 Minutes") == 4200


def test_parse_uptime_minutes_only():
    assert _parse_uptime("45 Minutes") == 2700


def test_parse_uptime_days_hours_minutes():
    assert _parse_uptime("3 Days, 2 Hours, 5 Minutes") == 3 * 86400 + 2 * 3600 + 5 * 60


def test_parse_uptime_unparseable_returns_none():
    assert _parse_uptime("garbage response") is None


def test_normalize_poly_datetime_converts_colon_separator_to_t():
    assert _normalize_poly_datetime("2026-07-28:14:00") == "2026-07-28T14:00:00"


def test_normalize_poly_datetime_only_replaces_date_time_separator():
    # 시:분 사이의 ":"는 그대로 남아야 한다 — 첫 ":"(날짜/시간 경계)만 "T"로 바뀐다.
    result = _normalize_poly_datetime("2026-01-05:09:30")
    assert result == "2026-01-05T09:30:00"
    assert result.count(":") == 2
