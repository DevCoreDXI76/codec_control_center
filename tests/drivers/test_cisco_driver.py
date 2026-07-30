import pytest
import pytest_asyncio

from app.core.driver_base import CalendarEntry, DriverCommandError, DriverTimeoutError
from app.drivers.cisco import cisco_commands as cisco_cmd
from app.drivers.cisco.cisco_driver import CiscoDriver, _check_result_ok
from app.simulator.cisco_sim_server import CiscoSimServer


@pytest_asyncio.fixture
async def sim_and_driver():
    sim = CiscoSimServer(host="127.0.0.1", port=0)
    sim.start()

    driver = CiscoDriver(host="127.0.0.1", port=sim.port, username="admin", password="x", timeout=5.0)
    await driver.connect()
    try:
        yield sim, driver
    finally:
        await driver.disconnect()
        sim.stop()


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
    assert await driver.dial("1234@example.com") is True
    assert sim.state.in_call is True

    status = await driver.get_status()
    assert status.in_call is True
    assert status.call_peer == "1234@example.com"


async def test_hangup_clears_call(sim_and_driver):
    sim, driver = sim_and_driver
    await driver.dial("1234@example.com")
    assert await driver.hangup() is True
    assert sim.state.in_call is False

    status = await driver.get_status()
    assert status.in_call is False


async def test_reboot_returns_true_without_hanging(sim_and_driver):
    _sim, driver = sim_and_driver
    assert await driver.reboot() is True


async def test_get_calendar_status_registered_when_bookings_present(sim_and_driver):
    _sim, driver = sim_and_driver
    assert await driver.get_calendar_status() == "registered"


async def test_get_calendar_status_registered_when_no_bookings(sim_and_driver):
    sim, driver = sim_and_driver
    sim.state.bookings = []
    # 예약이 없어도 Bookings Availability Status 자체는 응답하므로 기능은 "registered"
    assert await driver.get_calendar_status() == "registered"


async def test_get_obtp_entries_returns_seeded_meeting(sim_and_driver):
    _sim, driver = sim_and_driver
    entries = await driver.get_obtp_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, CalendarEntry)
    assert entry.subject == "주간 전체회의"
    assert entry.join_uri == "sip:weekly@example.com"


async def test_get_obtp_entries_empty_when_no_bookings(sim_and_driver):
    sim, driver = sim_and_driver
    sim.state.bookings = []
    entries = await driver.get_obtp_entries()
    assert entries == []


async def test_cisco_join_meeting_from_obtp_entry(sim_and_driver):
    sim, driver = sim_and_driver
    entries = await driver.get_obtp_entries()
    assert await driver.join_meeting(entries[0]) is True
    assert sim.state.in_call is True
    assert sim.state.call_peer == "sip:weekly@example.com"


async def test_join_meeting_dials_join_uri(sim_and_driver):
    sim, driver = sim_and_driver
    entry = CalendarEntry(subject="Weekly", start_time="x", end_time="y", join_uri="sip:weekly@example.com")
    assert await driver.join_meeting(entry) is True
    assert sim.state.in_call is True
    assert sim.state.call_peer == "sip:weekly@example.com"


async def test_join_meeting_without_uri_raises(sim_and_driver):
    _sim, driver = sim_and_driver
    entry = CalendarEntry(subject="No URI", start_time="x", end_time="y", join_uri=None)
    with pytest.raises(Exception):
        await driver.join_meeting(entry)


async def test_full_lifecycle_no_exceptions(sim_and_driver):
    """Phase① DoD: connect/get_status/mute/dial/hangup/reboot 전부 예외 없이 동작."""
    _sim, driver = sim_and_driver
    await driver.get_status()
    await driver.mute(True)
    await driver.mute(False)
    await driver.dial("1234")
    await driver.hangup()
    await driver.reboot()


# --- _check_result_ok (Cisco 오류 케이스 처리) ---


def test_check_result_ok_true_on_status_ok():
    lines = ["*r AudioMicrophonesMuteResult (status=OK):"]
    assert _check_result_ok(lines, "*r AudioMicrophonesMuteResult") is True


def test_check_result_ok_raises_with_device_response_on_error_status():
    lines = ['*r AudioMicrophonesMuteResult (status=Error): Reason: "insufficient permission"']
    with pytest.raises(DriverCommandError, match="insufficient permission"):
        _check_result_ok(lines, "*r AudioMicrophonesMuteResult")


def test_check_result_ok_raises_on_unexpected_response():
    lines = ["some completely unrelated line"]
    with pytest.raises(DriverCommandError, match="unexpected response"):
        _check_result_ok(lines, "*r AudioMicrophonesMuteResult")


def test_check_result_ok_raises_on_empty_response():
    with pytest.raises(DriverCommandError, match="empty response"):
        _check_result_ok([], "*r AudioMicrophonesMuteResult")


async def test_get_status_includes_model_and_uptime(sim_and_driver):
    _sim, driver = sim_and_driver
    status = await driver.get_status()
    assert status.model == "Room Kit Pro (SIM)"
    assert status.uptime_seconds == 7384


def test_get_status_uptime_failure_still_reports_online():
    """uptime 조회(STATUS_SYSTEMUNIT_UPTIME)만 실패해도 mute/call 상태 조회는 정상
    진행되어 online=True를 유지해야 한다 — Poly 드라이버에서 발견된 것과 같은 문제
    (uptime 조회 실패가 get_status() 전체를 offline으로 끌어내림)가 Cisco 드라이버의
    _get_status_sync에도 있는지 검증한다. 시뮬레이터가 아직 이 명령에 응답하지
    않으므로(Task 5 완료 전) 실제 소켓 통신 대신 _call_block_sync를 스텁으로 교체해
    STATUS_SYSTEMUNIT_UPTIME 호출에만 DriverError를 주입한다."""
    driver = CiscoDriver(host="127.0.0.1", port=1, username="admin", password="x")
    driver._model = "Room Kit Pro (SIM)"

    def fake_call_block_sync(command, end="** end"):
        if command == cisco_cmd.STATUS_SYSTEMUNIT_UPTIME:
            raise DriverTimeoutError("timeout waiting for device response")
        if command == cisco_cmd.STATUS_AUDIO_MUTE:
            return ["*s Audio Microphones Mute: Off"]
        if command == cisco_cmd.STATUS_CALL:
            return []
        raise AssertionError(f"unexpected command in test stub: {command}")

    driver._call_block_sync = fake_call_block_sync

    status = driver._get_status_sync("2026-07-30T00:00:00+00:00")

    assert status.online is True
    assert status.error is None
    assert status.uptime_seconds is None
    assert status.model == "Room Kit Pro (SIM)"
