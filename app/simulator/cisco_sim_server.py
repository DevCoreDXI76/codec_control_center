# app/simulator/cisco_sim_server.py
"""
Cisco RoomOS xAPI를 흉내 내는 SSH 모의 서버.

app/drivers/cisco/cisco_commands.py에서 문서 대조로 확정한 명령/응답 포맷만 처리한다.
paramiko는 동기(블로킹) API이므로 서버는 스레드 기반으로 동작한다
(비동기 CiscoDriver는 asyncio.to_thread로 이 블로킹 소켓을 감싼다).

기본 포트 127.0.0.1:2222 (SPEC.md 10절 기준).
"""
from __future__ import annotations

import socket
import threading
from dataclasses import dataclass

import paramiko


@dataclass
class CiscoSimState:
    muted: bool = False
    in_call: bool = False
    call_id: str = "27"
    call_peer: str | None = None


class _CiscoServerInterface(paramiko.ServerInterface):
    def __init__(self) -> None:
        self.shell_requested = threading.Event()

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username: str, password: str) -> int:
        return paramiko.AUTH_SUCCESSFUL  # 시뮬레이터: 자격증명 검증하지 않음

    def get_allowed_auths(self, username: str) -> str:
        return "password"

    def check_channel_shell_request(self, channel) -> bool:
        self.shell_requested.set()
        return True

    def check_channel_pty_request(self, *args, **kwargs) -> bool:
        return True


class CiscoSimServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 2222) -> None:
        self.host = host
        self.port = port
        self.state = CiscoSimState()
        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._running = False
        self._host_key = paramiko.RSAKey.generate(2048)

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client_sock, _addr = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()

    def _handle_client(self, client_sock: socket.socket) -> None:
        transport = paramiko.Transport(client_sock)
        transport.add_server_key(self._host_key)
        server = _CiscoServerInterface()
        try:
            transport.start_server(server=server)
            channel = transport.accept(20)
            if channel is None:
                return
            server.shell_requested.wait(10)
            self._shell_loop(channel)
        except (paramiko.SSHException, OSError):
            pass
        finally:
            transport.close()

    def _shell_loop(self, channel) -> None:
        buffer = b""
        while True:
            try:
                data = channel.recv(4096)
            except OSError:
                break
            if not data:
                break
            buffer += data
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                command = raw_line.decode("utf-8", errors="replace").strip()
                if not command:
                    continue
                response = self.handle(command)
                if response is not None:
                    try:
                        channel.send((response + "\r\n").encode("utf-8"))
                    except OSError:
                        return

    # --- 명령 처리 (소켓과 분리 — 단독 단위 테스트 가능) ---
    def handle(self, command: str) -> str | None:
        if command == "xCommand Audio Microphones Mute":
            self.state.muted = True
            return "*r AudioMicrophonesMuteResult (status=OK):\r\n** end"
        if command == "xCommand Audio Microphones Unmute":
            self.state.muted = False
            return "*r AudioMicrophonesUnmuteResult (status=OK):\r\n** end"
        if command == "xStatus Audio Microphones Mute":
            value = "On" if self.state.muted else "Off"
            return f"*s Audio Microphones Mute: {value}\r\n** end"
        if command.startswith("xCommand Dial Number:"):
            number = _extract_quoted(command)
            self.state.in_call = True
            self.state.call_peer = number
            return (
                "*r DialResult (status=OK):\r\n"
                f"  CallId: {self.state.call_id}\r\n"
                "** end"
            )
        if command == "xCommand Call Disconnect" or command.startswith("xCommand Call Disconnect CallId:"):
            self.state.in_call = False
            self.state.call_peer = None
            return "*r CallDisconnectResult (status=OK):\r\n** end"
        if command == "xStatus Call":
            if not self.state.in_call:
                return "** end"
            return (
                f'*s Call {self.state.call_id} DisplayName: "{self.state.call_peer}"\r\n'
                f'*s Call {self.state.call_id} RemoteNumber: "{self.state.call_peer}"\r\n'
                "** end"
            )
        if command == "xCommand SystemUnit Boot Action: Restart":
            # 문서상 재부팅 명령은 실행 즉시 세션이 끊기는 것이 일반적 동작이라
            # 별도 피드백 없이 상태만 초기화한다 (Poly reboot과 동일한 설계 원칙).
            self.state.muted = False
            self.state.in_call = False
            self.state.call_peer = None
            return None
        return None


def _extract_quoted(command: str) -> str:
    start = command.find('"')
    end = command.rfind('"')
    if start != -1 and end != -1 and end > start:
        return command[start + 1 : end]
    return command.split(":", 1)[-1].strip()
