import asyncio
import socket

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


def _stub_call_expecting(driver, fake_call):
    """_call_expecting은 _call과 별도 메서드라 driver._call만 바꿔서는 가로채지지
    않는다 — is_valid 판정 없이 그대로 fake_call에 위임하도록 함께 바꿔준다."""
    driver._call = fake_call
    driver._call_expecting = lambda command, is_valid: fake_call(command)


async def test_mute_raises_with_raw_response_on_mismatch():
    driver = PolyDriver(host="127.0.0.1", port=1)
    _stub_call_expecting(driver, lambda command: _async_return("some unexpected text"))
    with pytest.raises(DriverCommandError, match="some unexpected text"):
        await driver.mute(True)


async def test_dial_raises_with_raw_response_on_mismatch():
    driver = PolyDriver(host="127.0.0.1", port=1)
    _stub_call_expecting(driver, lambda command: _async_return("busy"))
    with pytest.raises(DriverCommandError, match="busy"):
        await driver.dial("1234")


async def test_hangup_raises_with_raw_response_on_mismatch():
    driver = PolyDriver(host="127.0.0.1", port=1)
    _stub_call_expecting(driver, lambda command: _async_return("no active call"))
    with pytest.raises(DriverCommandError, match="no active call"):
        await driver.hangup()


async def _async_return(value):
    return value


async def test_join_meeting_raises_with_raw_response_on_mismatch():
    """join_meeting()이 dial()/hangup()/mute()와 달리 예전 _call()을 그대로 쓰고 있어서,
    응답이 밀려도 그냥 조용히 False만 반환하던 버그(2026-07-31 VDI 2차 재테스트 —
    Poly 장비에서 Teams 회의 링크 참가는 실패하는데 회의ID 직접 다이얼은 되던 원인).
    이제 dial()과 동일하게 원인을 담아 예외로 올려야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    _stub_call_expecting(driver, lambda command: _async_return("busy"))
    entry = CalendarEntry(
        subject="주간 전체회의", start_time="", end_time="", join_uri="sip:weekly@example.com"
    )
    with pytest.raises(DriverCommandError, match="busy"):
        await driver.join_meeting(entry)


async def test_join_meeting_recovers_from_lagged_response():
    """다이얼과 마찬가지로 join_meeting()도 응답이 한 교환 밀려 들어와도 성공을
    인식해야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    lines = iter(["mute near off", "dialing sip:weekly@example.com"])

    async def fake_send(command):
        return None

    async def fake_read_line_once():
        return next(lines)

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once
    entry = CalendarEntry(
        subject="주간 전체회의", start_time="", end_time="", join_uri="sip:weekly@example.com"
    )

    assert await driver.join_meeting(entry) is True


async def test_get_status_extracts_call_peer_from_real_callinfo_format():
    """2026-07-31 VDI 2차 재테스트에서 실장비 원문으로 확보:
    "callinfo:1::1330378709@vc.poscodx.com:384:connected:notmuted:outgoing:videocall" —
    call.id 다음 필드(index 2)가 비어 있고 주소는 index 3에 온다. 예전 코드는 index 2를
    읽어서 항상 빈 문자열이 됐고, 그 결과 Teams 회의 목록과 매칭이 안 돼 통화 중에도
    카드에 회의 제목이 안 뜨던 버그(Cisco 카드에는 떴는데 Poly만 안 뜬 이유)."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._model = "RealPresence Group 700"
    lines = iter(
        [
            "mute near off",
            "callinfo begin",
            "callinfo:1::1330378709@vc.poscodx.com:384:connected:notmuted:outgoing:videocall",
            "callinfo end",
            "1 Hour, 0 Minutes",
        ]
    )

    async def fake_send(command):
        return None

    async def fake_read_line_once():
        return next(lines)

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once

    status = await driver.get_status()

    assert status.in_call is True
    assert status.call_peer == "1330378709@vc.poscodx.com"


async def test_join_meeting_uses_dial_manual_not_dial_phone():
    """2026-07-31 VDI 2차 재테스트 실장비 원문 확인 — `dial phone sip "..."`(dial_phone)에
    장비가 "info: AUDIO call not enabled"로 응답해 거부함. direct-dial이 쓰는
    `dial manual`(dial_manual)은 같은 주소로 정상 동작해서 join_meeting()도 이걸 쓰도록
    바꿨다 — 실제로 보낸 명령이 dial_phone이 아니라 dial_manual 형식인지 확인."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    sent: list[str] = []

    async def fake_send(command):
        sent.append(command)

    async def fake_read_line_once():
        return "dialing 1330378709@vc.poscodx.com"

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once
    entry = CalendarEntry(
        subject="BridgeX 테스트", start_time="", end_time="", join_uri="1330378709@vc.poscodx.com"
    )

    assert await driver.join_meeting(entry) is True
    assert sent == [poly_cmd.dial_manual("1330378709@vc.poscodx.com")]
    assert "phone" not in sent[0]


async def test_call_expecting_stops_immediately_on_info_line_instead_of_skipping():
    """2026-07-31 VDI 2차 재테스트에서 실제로 확인 — "info: AUDIO call not enabled"는
    밀려 들어온 잡음이 아니라 장비가 방금 보낸 명령을 거부한 진짜 응답이었다. 이걸
    잡음으로 보고 계속 건너뛰면 결국 응답이 끊겨 "timeout waiting for device response"로만
    보이고 진짜 이유(거부 사유)가 묻힌다. is_valid를 통과 못 해도 "info: "로 시작하면
    곧장 반환해야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    lines = iter(["info: AUDIO call not enabled", "이 줄까지 오면 안 됨(더 못 읽어야 정상)"])

    async def fake_send(command):
        return None

    async def fake_read_line_once():
        return next(lines)

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once

    resp = await driver._call_expecting(poly_cmd.MUTE_NEAR_GET, lambda line: line.startswith("dialing"))

    assert resp == "info: AUDIO call not enabled"


async def test_fetch_model_recognizes_self_description_block_format():
    """2026-07-31 VDI 2차 재테스트에서 실장비 원문으로 확인 — 세션이 스스로 보내는
    자기소개 블록("Here is what I know about myself:" 뒤)에도 "Model:  <값>" 형태로
    모델명이 나온다. 인용부호로 감싼 형태(systemsetting model "...")뿐 아니라 이 형태도
    인식해야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    lines = iter(["Here is what I know about myself:", "Model:               RealPresence Group 700"])

    async def fake_send(command):
        return None

    async def fake_read_line_once():
        return next(lines)

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once

    await driver._fetch_model()

    assert driver._model == "RealPresence Group 700"


async def test_call_expecting_survives_full_self_description_banner():
    """2026-07-31 VDI 2차 재테스트 /logs 원문 그대로(축약) — 자기소개 블록이 13줄 넘게
    이어지며 mute/callinfo 자리에 끼어드는 것이 실제로 확인됨. 이전 재시도 한도(3)로는
    부족해서 늘렸다(25) — 이 정도 길이의 잡음은 통과해서 진짜 응답을 찾아야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    banner = [
        "Here is what I know about myself:",
        "Model:               RealPresence Group 700",
        "Software Version:    6.2.1",
        "Build Information:   540239",
        "Contact Number:",
        "Total Time In Calls: 21 Days, 04:43:14",
        "Total Calls:         666",
        "SNTP Time Service:   Auto",
        "Local Time is:        Fri, 31 Jul 2026 19:05:33 +0900",
        "IP Video Number:     203.238.221.26",
        "MP Enabled:          KA2E-C657-9700-0000-0003",
        "H323 Enabled:        True",
    ]
    lines = iter([*banner, "mute near off"])

    async def fake_send(command):
        return None

    async def fake_read_line_once():
        return next(lines)

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once

    resp = await driver._call_expecting(
        poly_cmd.MUTE_NEAR_GET, lambda line: line in ("mute near on", "mute near off")
    )

    assert resp == "mute near off"


# --- 2026-07-31 VDI 2차 재테스트: 실제로는 통화중이 아닌데 새로고침을 해도 계속
# "통화중"으로 표시되던 재발 버그. callinfo 응답이 "callinfo begin"도 "system is not
# in a call"도 아닌 예상 밖의 한 줄(세션이 뒤섞여 다른 명령의 응답이 끼어든 경우 등)로
# 오면, 기존 코드는 그 줄을 "not in a call" 문자열과 다르다는 이유만으로 무조건
# in_call=True로 확정해버렸다 — 실패가 아니라 "정상인데 통화중"으로 보이니 로그도
# 전혀 안 남았다. 이제는 예상 밖 응답이면 DriverCommandError로 올려 get_status()가
# online=False+error로 보고하게 한다(무조건 in_call=True로 fail-open하지 않음).


async def test_get_status_reports_error_instead_of_false_in_call_on_desync():
    """_call_block은 그대로 두고(실제 검증 로직을 타야 함) 그 아래 계층인 _call만
    가짜로 대체해, 세션이 뒤섞여 callinfo 자리에 엉뚱한 줄이 온 상황을 재현한다.
    callinfo는 계속 같은 잘못된 줄을 돌려주므로 _call_expecting의 재시도(최대
    _MAX_LAG_SKIPS번)를 다 써도 끝내 못 찾고 그 줄을 그대로 반환해야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._model = "Group 700"

    async def fake_call(command):
        if command == poly_cmd.MUTE_NEAR_GET:
            return "mute near off"
        if command == poly_cmd.CALLINFO_ALL:
            return "notify:callstatus:something unrelated"
        if command == poly_cmd.UPTIME_GET:
            return "1 Hour, 0 Minutes"
        raise AssertionError(f"unexpected command in test stub: {command}")

    _stub_call_expecting(driver, fake_call)

    status = await driver.get_status()

    assert status.online is False
    assert status.in_call is False
    assert "notify:callstatus:something unrelated" in status.error


async def test_call_block_raises_on_unexpected_single_line_when_strict():
    driver = PolyDriver(host="127.0.0.1", port=1)
    _stub_call_expecting(driver, lambda command: _async_return("garbage"))
    with pytest.raises(DriverCommandError, match="garbage"):
        await driver._call_block(
            "callinfo all", "callinfo begin", "callinfo end", allow_single_line="system is not in a call"
        )


async def test_read_line_skips_unsolicited_greeting():
    """실장비가 세션 중 아무 때나(명령 흐름과 무관하게) 인사말 줄을 스스로 보낼 수 있다
    ("Hi, my name is : <장비 이름>") — 2026-07-31 VDI 2차 재테스트에서 이 줄이 callinfo
    응답 자리에 끼어들어 세션이 영구히 밀리는 것으로 실제 확인됨. _read_line()이 이
    줄을 만나면 버리고 다음 줄을 읽어야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    responses = iter(["Hi, my name is : 판교 6층 영상회의실", "mute near off"])

    async def fake_read_line_once():
        return next(responses)

    driver._read_line_once = fake_read_line_once

    assert await driver._read_line() == "mute near off"


async def test_get_obtp_entries_parses_real_empty_response_with_prompt_echo_noise():
    """2026-07-31 VDI 2차 재테스트에서 사용자가 실장비에 직접 접속해 확보한 원문 —
    회의가 없을 때는 "calendarmeetings list begin" 바로 뒤에 내용 없이
    "calendarmeetings list end"가 온다(추측이 아니라 실측 확인). 앞에 프롬프트 에코
    ("-> calendarmeetings list "today"")가 섞여 들어와도 빈 목록으로 정상 파싱돼야
    한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    lines = iter(
        [
            '-> calendarmeetings list "today"',
            "calendarmeetings list begin",
            "calendarmeetings list end",
        ]
    )

    async def fake_send(command):
        return None

    async def fake_read_line_once():
        return next(lines)

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once

    entries = await driver.get_obtp_entries()

    assert entries == []


async def test_call_expecting_skips_past_lagged_response_from_previous_command():
    """실장비 /logs 원문 트레이스에서 확인된 패턴 — 어떤 명령의 진짜 응답이 그 다음
    명령의 응답 자리에서 나온다(2026-07-31 VDI 2차 재테스트, 같은 모양이 5회 이상
    재현됨: mute의 진짜 응답이 callinfo 자리에서, model의 진짜 응답이 mute 자리에서
    나오는 식). 기대하는 모양(is_valid)이 아닌 줄이 먼저 나와도 곧장 포기하지 않고
    몇 줄 더 읽어 진짜 응답을 찾아야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    lines = iter(['systemsetting model "RealPresence Group 700"', "mute near off"])

    async def fake_send(command):
        return None

    async def fake_read_line_once():
        return next(lines)

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once

    resp = await driver._call_expecting(
        poly_cmd.MUTE_NEAR_GET, lambda line: line in ("mute near on", "mute near off")
    )

    assert resp == "mute near off"


async def test_call_expecting_gives_up_after_max_lag_skips_and_returns_last_line():
    """_MAX_LAG_SKIPS를 다 써도 그럴듯한 줄을 못 찾으면 무한정 기다리지 않고 마지막으로
    읽은 줄을 그대로 반환한다 — 호출부(예: mute()의 불일치 검사)가 실패를 판단하도록
    맡긴다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    total_reads = driver._MAX_LAG_SKIPS + 1
    lines = iter([f"garbage{i}" for i in range(1, total_reads + 1)])

    async def fake_send(command):
        return None

    async def fake_read_line_once():
        return next(lines)

    driver._send = fake_send
    driver._read_line_once = fake_read_line_once

    resp = await driver._call_expecting(poly_cmd.MUTE_NEAR_GET, lambda line: line == "mute near on")

    assert resp == f"garbage{total_reads}"


async def test_read_line_skips_prompt_echo():
    """장비 셸이 "-> " 프롬프트 뒤에 (때로는 몇 교환 뒤늦게) 이전에 받은 명령을 그대로
    에코해 돌려보낸다 — 2026-07-31 VDI 2차 재테스트 /logs 원문 트레이스에서
    "-> systemsetting get model", "-> calendarmeetings list "today""로 확인됨.
    "-> "로 시작하는 줄은 실제 데이터 응답이었던 적이 한 번도 없다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    responses = iter(['-> systemsetting get model', "mute near off"])

    async def fake_read_line_once():
        return next(responses)

    driver._read_line_once = fake_read_line_once

    assert await driver._read_line() == "mute near off"


async def test_read_line_skips_blank_lines():
    """실장비 /logs 원문 트레이스에서 빈 줄이 반복적으로 응답 자리에 끼어드는 게
    확인됐다(2026-07-31 VDI 2차 재테스트) — 이 드라이버가 다루는 어떤 명령도 빈 줄을
    정상 응답으로 반환한 적이 없으므로 무조건 잡음으로 간주하고 버린다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    responses = iter(["", "", "mute near off"])

    async def fake_read_line_once():
        return next(responses)

    driver._read_line_once = fake_read_line_once

    assert await driver._read_line() == "mute near off"


class _FakeTelnetReader:
    """readline()이 미리 준비된 줄을 순서대로 반환하다가, 소진되면 응답 없이 오래
    대기해 _drain_startup_noise_telnet()의 짧은 타임아웃이 실제로 발동하는지 검증한다."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    async def readline(self):
        if self._lines:
            return self._lines.pop(0) + "\n"
        await asyncio.sleep(10)


async def test_drain_startup_noise_telnet_consumes_unknown_number_of_lines():
    """인사말이 몇 줄일지 미리 알 수 없다("Hi, my name is..." 뒤에 "Here is what I
    know about myself:" 등 몇 줄이 더 있을지는 문서에 없음, 2026-07-31 확인) — 정확한
    줄 수를 가정하지 않고 조용해질 때까지 전부 비워야 한다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._reader = _FakeTelnetReader(
        [
            "Hi, my name is :     판교 6층 영상회의실",
            "Here is what I know about myself:",
            "  some more self-description",
        ]
    )
    driver._STARTUP_DRAIN_PER_READ_TIMEOUT = 0.05

    await driver._drain_startup_noise_telnet()

    assert len(driver._recent_lines) == 3


class _FakeSSHChannel:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def settimeout(self, value: float) -> None:
        pass

    def recv(self, n: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        raise socket.timeout()


def test_drain_startup_noise_ssh_sync_consumes_unknown_number_of_lines():
    driver = PolyDriver(host="127.0.0.1", port=1, transport="ssh")
    driver._ssh_channel = _FakeSSHChannel([b"line one\n", b"line two\n"])
    driver._STARTUP_DRAIN_PER_READ_TIMEOUT = 0.05

    driver._drain_startup_noise_ssh_sync()

    assert len(driver._recent_lines) == 2


async def test_call_block_lenient_mode_unchanged_for_other_callers():
    """allow_single_line을 안 주면 기존 동작(임의의 단일 줄도 그대로 반환) 그대로 —
    calendarmeetings 등 다른 호출부의 동작을 바꾸지 않는다."""
    driver = PolyDriver(host="127.0.0.1", port=1)
    driver._call = lambda command: _async_return("anything")
    result = await driver._call_block("cmd", "begin marker", "end marker")
    assert result == ["anything"]


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

    async def fake_call_block(command, begin, end, *, allow_single_line=None):
        return ["system is not in a call"]

    _stub_call_expecting(driver, fake_call)
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

    async def fake_call_block(command, begin, end, *, allow_single_line=None):
        return ["system is not in a call"]

    _stub_call_expecting(driver, fake_call)
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
