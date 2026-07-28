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
