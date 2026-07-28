import telnetlib3
import pytest

from app.simulator.poly_sim_server import PolySimServer


# --- 순수 상태-머신 단위 테스트 (소켓 없이 handle()만 검증) ---


def test_mute_get_default_off():
    sim = PolySimServer()
    assert sim.handle("mute near get") == "mute near off"


def test_mute_on_off_toggle_updates_state():
    sim = PolySimServer()
    assert sim.handle("mute near on") == "mute near on"
    assert sim.state.muted is True
    assert sim.handle("mute near off") == "mute near off"
    assert sim.state.muted is False


def test_mute_far_get():
    sim = PolySimServer()
    assert sim.handle("mute far get") == "mute far off"


def test_dial_manual_sets_in_call():
    sim = PolySimServer()
    resp = sim.handle('dial manual "384" "5551212"')
    assert resp == 'dialing manual "5551212"'
    assert sim.state.in_call is True
    assert sim.state.call_peer == "5551212"


def test_dial_phone_sip():
    sim = PolySimServer()
    resp = sim.handle('dial phone sip "1234"')
    assert resp == "dialing voice_sip"
    assert sim.state.in_call is True


def test_hangup_clears_call():
    sim = PolySimServer()
    sim.handle('dial phone sip "1234"')
    resp = sim.handle("hangup video")
    assert resp == "hanging up video"
    assert sim.state.in_call is False
    assert sim.state.call_peer is None


def test_reboot_resets_state_and_returns_no_feedback():
    sim = PolySimServer()
    sim.handle("mute near on")
    sim.handle('dial phone sip "1234"')
    resp = sim.handle("reboot now")
    assert resp is None
    assert sim.state.muted is False
    assert sim.state.in_call is False


def test_callinfo_no_call():
    sim = PolySimServer()
    assert sim.handle("callinfo all") == "system is not in a call"


def test_callinfo_during_call():
    sim = PolySimServer()
    sim.handle('dial phone sip "1234"')
    resp = sim.handle("callinfo all")
    assert resp.startswith("callinfo begin")
    assert "connected" in resp
    assert resp.endswith("callinfo end")


def test_calendarstatus_established_by_default():
    sim = PolySimServer()
    assert sim.handle("calendarstatus get") == "calendarstatus established"


def test_calendarmeetings_list_and_info():
    sim = PolySimServer()
    list_resp = sim.handle('calendarmeetings list "today"')
    assert list_resp.startswith("calendarmeetings list begin")
    assert "meeting|meeting-001|" in list_resp

    info_resp = sim.handle('calendarmeetings info "meeting-001"')
    assert "subject|주간 전체회의" in info_resp
    assert "dialingnumber|video|sip:weekly@example.com|sip" in info_resp


def test_unknown_command_returns_none():
    sim = PolySimServer()
    assert sim.handle("no_such_command") is None


# --- 실제 Telnet 소켓 통합 테스트 (server 기동 -> client 접속 -> 명령/응답) ---


async def test_telnet_server_end_to_end():
    sim = PolySimServer(host="127.0.0.1", port=0)
    await sim.start()
    port = sim._server.sockets[0].getsockname()[1]
    try:
        reader, writer = await telnetlib3.open_connection("127.0.0.1", port)
        try:
            writer.write("mute near on\r\n")
            line = await reader.readline()
            assert line.strip() == "mute near on"
        finally:
            writer.close()
    finally:
        await sim.stop()
