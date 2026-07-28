# app/simulator/poly_sim_server.py
"""
Poly (Polycom RealPresence Group Series) API를 흉내 내는 Telnet 모의 서버.

app/drivers/poly/poly_commands.py에서 문서(Integrator Reference Guide) 대조로
확정한 명령/응답 포맷만 처리한다. 문서에 없는 명령은 추가하지 않는다.

기본 포트 127.0.0.1:2323 (SPEC.md 10절 기준).
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field

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
        line = (
            f"callinfo:{self.state.call_id}:{self.state.call_peer}:"
            f"{self.state.call_peer}:384:connected:{mute_word}:outgoing:videocall"
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
