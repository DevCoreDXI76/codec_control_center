import time

import paramiko

from app.simulator.cisco_sim_server import CiscoSimServer


# --- 순수 상태-머신 단위 테스트 (소켓 없이 handle()만 검증) ---


def test_mute_unmute():
    sim = CiscoSimServer()
    resp = sim.handle("xCommand Audio Microphones Mute")
    assert resp.startswith("*r AudioMicrophonesMuteResult (status=OK):")
    assert sim.state.muted is True

    resp = sim.handle("xCommand Audio Microphones Unmute")
    assert resp.startswith("*r AudioMicrophonesUnmuteResult (status=OK):")
    assert sim.state.muted is False


def test_status_audio_mute():
    sim = CiscoSimServer()
    assert sim.handle("xStatus Audio Microphones Mute") == "*s Audio Microphones Mute: Off\r\n** end"
    sim.handle("xCommand Audio Microphones Mute")
    assert sim.handle("xStatus Audio Microphones Mute") == "*s Audio Microphones Mute: On\r\n** end"


def test_dial_sets_in_call():
    sim = CiscoSimServer()
    resp = sim.handle('xCommand Dial Number: "1234@example.com"')
    assert resp.startswith("*r DialResult (status=OK):")
    assert sim.state.in_call is True
    assert sim.state.call_peer == "1234@example.com"


def test_disconnect_clears_call():
    sim = CiscoSimServer()
    sim.handle('xCommand Dial Number: "1234@example.com"')
    resp = sim.handle("xCommand Call Disconnect")
    assert resp.startswith("*r CallDisconnectResult (status=OK):")
    assert sim.state.in_call is False
    assert sim.state.call_peer is None


def test_status_call_idle_and_in_call():
    sim = CiscoSimServer()
    assert sim.handle("xStatus Call") == "** end"

    sim.handle('xCommand Dial Number: "1234@example.com"')
    resp = sim.handle("xStatus Call")
    assert 'DisplayName: "1234@example.com"' in resp
    assert 'RemoteNumber: "1234@example.com"' in resp


def test_reboot_resets_state_no_feedback():
    sim = CiscoSimServer()
    sim.handle("xCommand Audio Microphones Mute")
    sim.handle('xCommand Dial Number: "1234@example.com"')
    resp = sim.handle("xCommand SystemUnit Boot Action: Restart")
    assert resp is None
    assert sim.state.muted is False
    assert sim.state.in_call is False


def test_unknown_command_returns_none():
    sim = CiscoSimServer()
    assert sim.handle("xCommand NoSuchThing") is None


def test_bookings_availability_status():
    sim = CiscoSimServer()
    resp = sim.handle("xStatus Bookings Availability Status")
    assert resp == "*s Bookings Availability Status: BookedUntil\r\n** end"

    sim.state.bookings = []
    resp = sim.handle("xStatus Bookings Availability Status")
    assert resp == "*s Bookings Availability Status: Free\r\n** end"


def test_bookings_list_returns_seeded_meeting():
    sim = CiscoSimServer()
    resp = sim.handle("xCommand Bookings List Days: 1 DayOffset: 0")
    assert resp.startswith("*r BookingsListResult (status=OK):")
    assert 'Booking 1 Id: "meeting-001"' in resp
    assert 'Booking 1 Title: "주간 전체회의"' in resp
    assert resp.endswith("** end")


def test_bookings_get_returns_detail():
    sim = CiscoSimServer()
    resp = sim.handle('xCommand Bookings Get Id: "meeting-001"')
    assert resp.startswith("*r BookingsGetResult (status=OK):")
    assert 'Booking Organizer FirstName: "Alex"' in resp
    assert 'Booking DialInfo Calls Call 1 Number: "sip:weekly@example.com"' in resp


def test_bookings_get_unknown_id_returns_error():
    sim = CiscoSimServer()
    resp = sim.handle('xCommand Bookings Get Id: "no-such-id"')
    assert "status=Error" in resp


# --- 실제 SSH 소켓 통합 테스트 (server 기동 -> paramiko client 접속 -> 명령/응답) ---


def test_ssh_server_end_to_end():
    sim = CiscoSimServer(host="127.0.0.1", port=0)
    sim.start()
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            "127.0.0.1",
            port=sim.port,
            username="admin",
            password="anything",
            timeout=5,
            look_for_keys=False,
            allow_agent=False,
        )
        try:
            channel = client.invoke_shell()
            channel.settimeout(5)
            channel.send("xCommand Audio Microphones Mute\n")

            deadline = time.time() + 5
            buffer = ""
            while "** end" not in buffer and time.time() < deadline:
                buffer += channel.recv(4096).decode("utf-8", errors="replace")
            assert "AudioMicrophonesMuteResult (status=OK)" in buffer
        finally:
            client.close()
    finally:
        sim.stop()
