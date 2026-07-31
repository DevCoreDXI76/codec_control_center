# app/simulator/poly_sim_server.py
"""
Poly (Polycom RealPresence Group Series) API를 흉내 내는 Telnet/SSH 모의 서버.

app/drivers/poly/poly_commands.py에서 문서(Integrator Reference Guide) 대조로
확정한 명령/응답 포맷만 처리한다. 문서에 없는 명령은 추가하지 않는다.
명령 처리(handle)는 Telnet/SSH 두 서버가 공유한다 — 접속 방식만 다를 뿐 API는 동일하다.

기본 포트: Telnet 127.0.0.1:2323, SSH 127.0.0.1:2222 (SPEC.md 10절 기준).
"""
from __future__ import annotations

import shlex
import socket
import threading
from dataclasses import dataclass, field

import paramiko
import telnetlib3


@dataclass
class MockMeeting:
    meeting_id: str
    start: str
    end: str
    subject: str
    organizer: str
    location: str
    dial_uri: str


@dataclass
class PolySimState:
    muted: bool = False
    in_call: bool = False
    call_peer: str | None = None
    call_id: str = "100"
    calendar_established: bool = True
    model: str = "RealPresence Group 500 (SIM)"
    uptime_text: str = "2 Hours, 5 Minutes"
    uptime_fails: bool = False  # True면 uptime get에 무응답 처리 → 드라이버 쪽 타임아웃/연결 오류 재현
    meetings: list[MockMeeting] = field(
        default_factory=lambda: [
            MockMeeting(
                meeting_id="meeting-001",
                start="2026-07-28:14:00",
                end="2026-07-28:15:00",
                subject="주간 전체회의",
                organizer="Alex MacDonald",
                location="3층 대회의실",
                dial_uri="sip:weekly@example.com",
            )
        ]
    )


class PolySimServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 2323) -> None:
        self.host = host
        self.port = port
        self.state = PolySimState()
        self._server: telnetlib3.Server | None = None

    async def start(self) -> None:
        self._server = await telnetlib3.create_server(
            host=self.host, port=self.port, shell=self._shell, encoding="utf8"
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _shell(self, reader, writer) -> None:
        while True:
            line = await reader.readline()
            if not line:
                break
            command = line.strip()
            if not command:
                continue
            response = self.handle(command)
            if response is not None:
                writer.write(response + "\r\n")

    # --- 명령 처리 (소켓과 분리 — 단독 단위 테스트 가능) ---
    def handle(self, command: str) -> str | None:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return None
        if not tokens:
            return None

        verb = tokens[0]
        if verb == "mute":
            return self._handle_mute(tokens)
        if verb == "dial":
            return self._handle_dial(tokens)
        if verb == "hangup":
            return self._handle_hangup(tokens)
        if verb == "reboot":
            return self._handle_reboot(tokens)
        if verb == "callinfo":
            return self._handle_callinfo(tokens)
        if verb == "calendarstatus":
            return self._handle_calendarstatus(tokens)
        if verb == "calendarmeetings":
            return self._handle_calendarmeetings(tokens)
        if verb == "systemsetting":
            return self._handle_systemsetting(tokens)
        if verb == "uptime":
            return self._handle_uptime(tokens)
        return None

    def _handle_mute(self, tokens: list[str]) -> str | None:
        if tokens[1:] == ["register"]:
            return "mute registered"
        if tokens[1:] == ["unregister"]:
            return "mute unregistered"
        if tokens[1:3] == ["near", "get"]:
            return "mute near on" if self.state.muted else "mute near off"
        if tokens[1:3] == ["near", "on"]:
            self.state.muted = True
            return "mute near on"
        if tokens[1:3] == ["near", "off"]:
            self.state.muted = False
            return "mute near off"
        if tokens[1:3] == ["near", "toggle"]:
            self.state.muted = not self.state.muted
            return "mute near on" if self.state.muted else "mute near off"
        if tokens[1:3] == ["far", "get"]:
            return "mute far off"
        return None

    def _handle_dial(self, tokens: list[str]) -> str | None:
        if tokens[1] == "manual" and len(tokens) >= 4:
            dialstr = tokens[3]
            self.state.in_call = True
            self.state.call_peer = dialstr
            return f'dialing manual "{dialstr}"'
        if tokens[1] == "phone" and len(tokens) >= 4:
            phone_type, dialstring = tokens[2], tokens[3]
            self.state.in_call = True
            self.state.call_peer = dialstring
            return "dialing voice_sip" if phone_type == "sip" else f"dialing voice_{phone_type}"
        if tokens[1] == "addressbook" and len(tokens) >= 3:
            name = tokens[2]
            self.state.in_call = True
            self.state.call_peer = name
            return f'dialing addressbook "{name}"'
        return None

    def _handle_hangup(self, tokens: list[str]) -> str | None:
        if tokens[1] in ("video", "all"):
            self.state.in_call = False
            self.state.call_peer = None
            return "hanging up video"
        return None

    def _handle_reboot(self, tokens: list[str]) -> str | None:
        # 문서: reboot now는 확인 없이 재시작하며 별도 피드백을 반환하지 않는다.
        self.state.muted = False
        self.state.in_call = False
        self.state.call_peer = None
        return None

    def _handle_callinfo(self, tokens: list[str]) -> str:
        if not self.state.in_call:
            return "system is not in a call"
        mute_word = "muted" if self.state.muted else "notmuted"
        # 실장비 원문 형식(2026-07-31 VDI 2차 재테스트로 확인):
        # "callinfo:<id>::<주소>:384:connected:...". call.id 다음 필드(index 2)가
        # 비어 있고 주소는 index 3에 온다 — 예전엔 이 빈 필드 없이 index 2에 주소를
        # 바로 넣어 시뮬레이터를 만들었는데, 그 잘못된 가정 때문에 드라이버가
        # call_peer를 엉뚱한(항상 빈) 필드에서 읽던 버그가 한동안 안 잡혔다.
        line = (
            f"callinfo:{self.state.call_id}::{self.state.call_peer}:"
            f"384:connected:{mute_word}:outgoing:videocall"
        )
        return "callinfo begin\r\n" + line + "\r\ncallinfo end"

    def _handle_calendarstatus(self, tokens: list[str]) -> str:
        return "calendarstatus established" if self.state.calendar_established else "calendarstatus unavailable"

    def _handle_calendarmeetings(self, tokens: list[str]) -> str:
        if tokens[1] == "list":
            lines = ["calendarmeetings list begin"]
            for m in self.state.meetings:
                lines.append(f"meeting|{m.meeting_id}|{m.start}|{m.end}|{m.subject}")
            lines.append("calendarmeetings list end")
            return "\r\n".join(lines)
        if tokens[1] == "info" and len(tokens) >= 3:
            meeting_id = tokens[2]
            match = next((m for m in self.state.meetings if m.meeting_id == meeting_id), None)
            if match is None:
                return "calendarmeetings info start\r\ncalendarmeetings info end"
            lines = [
                "calendarmeetings info start",
                f"id|{match.meeting_id}",
                f"{match.start}|{match.end}|dialable|public",
                f"organizer|{match.organizer}",
                f"location|{match.location}",
                f"subject|{match.subject}",
                f"dialingnumber|video|{match.dial_uri}|sip",
                "meetingpassword|none",
                "calendarmeetings info end",
            ]
            return "\r\n".join(lines)
        return None

    def _handle_systemsetting(self, tokens: list[str]) -> str | None:
        if tokens[1:3] == ["get", "model"]:
            return f'systemsetting model "{self.state.model}"'
        return None

    def _handle_uptime(self, tokens: list[str]) -> str | None:
        if tokens[1:] == ["get"]:
            if self.state.uptime_fails:
                return None  # 무응답 → 드라이버 _read_line이 타임아웃/연결종료로 처리
            return self.state.uptime_text
        return None


class _PolyServerInterface(paramiko.ServerInterface):
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


class PolySSHSimServer:
    """Poly API를 SSH 트랜스포트로 노출하는 모의 서버.

    명령 처리 로직(handle)과 상태는 PolySimServer 것을 그대로 재사용한다 —
    API는 Telnet/SSH 접속 방식과 무관하게 동일하기 때문이다.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 2222, restrict_to_ssh_rsa: bool = False) -> None:
        """restrict_to_ssh_rsa=True면 호스트키 협상 시 ssh-rsa(SHA-1)만 제시한다 —
        일부 실제 Poly Group Series 장비가 이 구형 알고리즘만 지원해서
        (2026-07-30 VDI 실장비 검증에서 `Incompatible ssh peer` 확인) 그 제약을
        재현하기 위한 테스트 전용 옵션. paramiko 5.x는 기본적으로 ssh-rsa를
        협상 목록/서명 해시 매핑에서 뺐으므로(poly_driver._allow_legacy_ssh_rsa_hostkey
        docstring 참고), 여기서도 같은 두 지점을 복구해야 서버가 실제로 ssh-rsa로
        서명할 수 있다."""
        self.host = host
        self.port = port
        self.restrict_to_ssh_rsa = restrict_to_ssh_rsa
        self._core = PolySimServer(host=host, port=0)
        self.state = self._core.state
        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._running = False
        self._host_key = paramiko.RSAKey.generate(2048)
        if restrict_to_ssh_rsa:
            if "ssh-rsa" not in paramiko.Transport._key_info:
                paramiko.Transport._key_info["ssh-rsa"] = paramiko.RSAKey
            if "ssh-rsa" not in paramiko.RSAKey.HASHES:
                from cryptography.hazmat.primitives import hashes

                paramiko.RSAKey.HASHES["ssh-rsa"] = hashes.SHA1

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
        if self.restrict_to_ssh_rsa:
            transport.get_security_options().key_types = ["ssh-rsa"]
        transport.add_server_key(self._host_key)
        server = _PolyServerInterface()
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
                response = self._core.handle(command)
                if response is not None:
                    try:
                        channel.send((response + "\r\n").encode("utf-8"))
                    except OSError:
                        return
