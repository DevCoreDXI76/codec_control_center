import pytest
import pytest_asyncio

from app.core.driver_base import CalendarEntry, DriverCommandError, DriverTimeoutError
from app.drivers.cisco import cisco_commands as cisco_cmd
from app.drivers.cisco.cisco_driver import CiscoDriver, _check_result_ok, _cisco_utc_to_kst_naive, _parse_bookings_list
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


# --- 2026-07-31 VDI 실장비 응답 원문 회귀 테스트: mute/unmute 결과 프리픽스 ---
# "*r AudioMicrophonesMuteResult"이 아니라 "*r MicrophonesMuteResult"("Audio" 없음)이며,
# 앞뒤에 echo성 노이즈 줄("OK", 명령 에코)이 섞여 있어도 정상 판정해야 한다.


def test_mute_handles_real_device_response_with_echo_noise():
    driver = CiscoDriver(host="127.0.0.1", port=1, username="admin", password="x")
    driver._call_block_sync = lambda command, end="** end": [
        "",
        "OK",
        "xCommand Audio Microphones Mute",
        "",
        "OK",
        "*r MicrophonesMuteResult (status=OK):",
    ]
    assert driver._mute_sync(True) is True


def test_unmute_handles_real_device_response_with_echo_noise():
    driver = CiscoDriver(host="127.0.0.1", port=1, username="admin", password="x")
    driver._call_block_sync = lambda command, end="** end": [
        "",
        "OK",
        "xCommand Audio Microphones Unmute",
        "",
        "OK",
        "*r MicrophonesUnmuteResult (status=OK):",
    ]
    assert driver._mute_sync(False) is True


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


# --- _parse_bookings_list (2026-07-31 VDI 실장비 응답 원문 회귀 테스트) ---
#
# 판교 6층 B회의실 Cisco 장비에서 "xCommand Bookings List Days: 1 DayOffset: 0"을 직접
# 실행해 받은 원문(줄 사이 공백/"OK" 에코 포함, 실제 터미널 출력 그대로) — 이전 파서는
# "*r BookingsListResult " 프리픽스를 고려하지 않아 모든 줄을 건너뛰고 빈 목록을
# 반환했다(Teams 일정이 하나도 안 잡히던 버그).
_REAL_BOOKINGS_LIST_RESPONSE = [
    "OK",
    "",
    "*r BookingsListResult (status=OK):",
    "",
    "*r BookingsListResult ResultInfo TotalRows: 1",
    "",
    '*r BookingsListResult LastUpdated: "2026-07-31T04:51:02Z"',
    "",
    '*r BookingsListResult Booking 1 Id: "c6f91f9a3eb655d4a17a8727399d760e"',
    "",
    '*r BookingsListResult Booking 1 MeetingId: ""',
    "",
    '*r BookingsListResult Booking 1 Title: "[회의실 예약] test"',
    "",
    '*r BookingsListResult Booking 1 Agenda: ""',
    "",
    "*r BookingsListResult Booking 1 Privacy: Public",
    "",
    '*r BookingsListResult Booking 1 Organizer FirstName: "강윤수(KANG"',
    "",
    '*r BookingsListResult Booking 1 Organizer LastName: "YUN SOO)_프로_인프라서비스섹션"',
    "",
    '*r BookingsListResult Booking 1 Organizer Email: "yunsoo.kang@poscodx.com"',
    "",
    '*r BookingsListResult Booking 1 Organizer Id: ""',
    "",
    '*r BookingsListResult Booking 1 Time StartTime: "2026-07-31T04:30:00Z"',
    "",
    "*r BookingsListResult Booking 1 Time StartTimeBuffer: 900",
    "",
    '*r BookingsListResult Booking 1 Time EndTime: "2026-07-31T06:00:00Z"',
    "",
    "*r BookingsListResult Booking 1 Time EndTimeBuffer: 0",
    "",
    "*r BookingsListResult Booking 1 MaximumMeetingExtension: 0",
    "",
    "*r BookingsListResult Booking 1 MeetingExtensionAvailability:",
    "",
    "*r BookingsListResult Booking 1 BookingStatus: OK",
    "",
    '*r BookingsListResult Booking 1 BookingStatusMessage: ""',
    "",
    '*r BookingsListResult Booking 1 MeetingPlatform: "MicrosoftTeams"',
    "",
    "*r BookingsListResult Booking 1 Cancellable: False",
    "",
    "*r BookingsListResult Booking 1 Webex Enabled: False",
    "",
    '*r BookingsListResult Booking 1 Webex Url: ""',
    "",
    '*r BookingsListResult Booking 1 Webex MeetingNumber: ""',
    "",
    '*r BookingsListResult Booking 1 Webex Password: ""',
    "",
    '*r BookingsListResult Booking 1 Webex HostKey: ""',
    "",
    "*r BookingsListResult Booking 1 Encryption: BestEffort",
    "",
    "*r BookingsListResult Booking 1 Recording: Disabled",
    "",
    '*r BookingsListResult Booking 1 DialInfo Calls Call 1 Number: "1314657531@vc.poscodx.com"',
    "",
    "*r BookingsListResult Booking 1 DialInfo Calls Call 1 CallType: Video",
    "",
    "*r BookingsListResult Booking 1 DialInfo ConnectMode: OBTP",
]


def test_parse_bookings_list_real_device_response():
    entries = _parse_bookings_list(_REAL_BOOKINGS_LIST_RESPONSE)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.subject == "[회의실 예약] test"
    # Cisco Bookings List는 UTC(Z 접미사)로 온다(실장비 원문으로 확인) — Poly와 동일하게
    # 프런트엔드가 다루는 naive KST 로컬시각으로 변환해서 담는다. 04:30 UTC = 13:30 KST.
    assert entry.start_time == "2026-07-31T13:30:00"
    assert entry.end_time == "2026-07-31T15:00:00"
    assert entry.join_uri == "1314657531@vc.poscodx.com"


def test_cisco_utc_to_kst_naive_converts_offset_correctly():
    assert _cisco_utc_to_kst_naive("2026-07-31T04:30:00Z") == "2026-07-31T13:30:00"


def test_cisco_utc_to_kst_naive_rolls_over_midnight():
    assert _cisco_utc_to_kst_naive("2026-07-31T20:00:00Z") == "2026-08-01T05:00:00"


def test_cisco_utc_to_kst_naive_returns_raw_on_unparseable_input():
    assert _cisco_utc_to_kst_naive("not-a-timestamp") == "not-a-timestamp"
    assert _cisco_utc_to_kst_naive("") == ""


def test_parse_bookings_list_empty_when_no_bookings():
    assert _parse_bookings_list(["OK", "", "*r BookingsListResult (status=OK):", "*r BookingsListResult ResultInfo TotalRows: 0"]) == []
