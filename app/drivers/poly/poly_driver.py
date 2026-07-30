# app/drivers/poly/poly_driver.py
"""
Poly (Polycom RealPresence Group Series) API 드라이버 — Telnet 또는 SSH.

Integrator Reference Guide 기준으로 API 명령 자체는 Telnet/SSH/RS-232 접속
방식과 무관하게 동일하다 (poly_commands.py에서 문서 대조로 확정한 명령만 사용).
Telnet은 telnetlib3(비동기 네이티브)를, SSH는 paramiko(동기)를
CiscoDriver와 동일하게 asyncio.to_thread로 감싸 사용한다.
"""
from __future__ import annotations

import asyncio
import re
import socket
from datetime import datetime, timezone

import paramiko
import telnetlib3

from app.core.driver_base import (
    CalendarEntry,
    DeviceDriver,
    DeviceStatus,
    DriverAuthError,
    DriverCommandError,
    DriverConnectionError,
    DriverError,
    DriverTimeoutError,
)
from . import poly_commands as cmd


class PolyDriver(DeviceDriver):
    def __init__(
        self,
        host: str,
        port: int = 2323,
        timeout: float = 7.0,
        transport: str = "telnet",
        username: str = "",
        password: str = "",
    ) -> None:
        if transport not in ("telnet", "ssh"):
            raise ValueError(f"invalid transport: {transport!r} (expected 'telnet' or 'ssh')")
        self.host = host
        self.port = port
        self.timeout = timeout
        self.transport = transport
        self.username = username
        self.password = password
        self._reader = None
        self._writer = None
        self._ssh_client: paramiko.SSHClient | None = None
        self._ssh_channel = None
        self._ssh_buffer = b""
        self._model: str | None = None

    async def connect(self) -> None:
        if self.transport == "ssh":
            await asyncio.to_thread(self._connect_ssh_sync)
        else:
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    telnetlib3.open_connection(self.host, self.port), timeout=self.timeout
                )
            except asyncio.TimeoutError as exc:
                raise DriverTimeoutError(f"connect timeout: {self.host}:{self.port}") from exc
            except OSError as exc:
                raise DriverConnectionError(str(exc)) from exc
        await self._fetch_model()

    async def _fetch_model(self) -> None:
        """모델명은 하드웨어가 바뀌지 않는 한 안 변하므로 연결 시 1회만 조회해 캐시한다.
        조회 실패는 connect() 전체를 실패시키지 않는다(있으면 좋은 정보일 뿐)."""
        try:
            resp = await self._call(cmd.SYSTEMSETTING_GET_MODEL)
        except DriverError:
            return
        match = re.search(r'"([^"]+)"', resp)
        if match:
            self._model = match.group(1)

    def _connect_ssh_sync(self) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        except paramiko.AuthenticationException as exc:
            raise DriverAuthError(str(exc)) from exc
        except (paramiko.SSHException, OSError) as exc:
            raise DriverConnectionError(str(exc)) from exc

        channel = client.invoke_shell()
        channel.settimeout(self.timeout)
        self._ssh_client = client
        self._ssh_channel = channel
        self._ssh_buffer = b""

    async def disconnect(self) -> None:
        if self.transport == "ssh":
            await asyncio.to_thread(self._disconnect_ssh_sync)
            return
        if self._writer is not None:
            self._writer.close()
        self._reader = None
        self._writer = None

    def _disconnect_ssh_sync(self) -> None:
        if self._ssh_channel is not None:
            try:
                self._ssh_channel.close()
            except (paramiko.SSHException, OSError, EOFError):
                pass
        if self._ssh_client is not None:
            try:
                self._ssh_client.close()
            except (paramiko.SSHException, OSError, EOFError):
                pass
        self._ssh_channel = None
        self._ssh_client = None

    # --- 내부 통신 헬퍼 ---

    async def _send(self, command: str) -> None:
        if self.transport == "ssh":
            await asyncio.to_thread(self._send_ssh_sync, command)
            return
        if self._writer is None:
            raise DriverConnectionError("not connected")
        try:
            self._writer.write(command + "\r\n")
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc

    def _send_ssh_sync(self, command: str) -> None:
        if self._ssh_channel is None:
            raise DriverConnectionError("not connected")
        try:
            self._ssh_channel.send(command + "\r\n")
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc

    async def _read_line(self) -> str:
        if self.transport == "ssh":
            return await asyncio.to_thread(self._read_line_ssh_sync)
        if self._reader is None:
            raise DriverConnectionError("not connected")
        try:
            line = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise DriverTimeoutError("timeout waiting for device response") from exc
        if not line:
            raise DriverConnectionError("connection closed by device")
        return line.strip()

    def _read_line_ssh_sync(self) -> str:
        if self._ssh_channel is None:
            raise DriverConnectionError("not connected")
        while b"\n" not in self._ssh_buffer:
            try:
                data = self._ssh_channel.recv(4096)
            except socket.timeout as exc:
                raise DriverTimeoutError("timeout waiting for device response") from exc
            except OSError as exc:
                raise DriverConnectionError(str(exc)) from exc
            if not data:
                raise DriverConnectionError("connection closed by device")
            self._ssh_buffer += data
        line, self._ssh_buffer = self._ssh_buffer.split(b"\n", 1)
        return line.decode("utf-8", errors="replace").strip()

    async def _call(self, command: str) -> str:
        await self._send(command)
        return await self._read_line()

    async def _call_block(self, command: str, begin: str, end: str) -> list[str]:
        """begin/end 마커로 감싸인 다중 라인 응답을 읽는다.
        마커 없이 단일 라인만 오면(예: "system is not in a call") 그 줄 하나만 담아 반환."""
        first = await self._call(command)
        if first != begin:
            return [first]
        lines: list[str] = []
        while True:
            line = await self._read_line()
            if line == end:
                break
            lines.append(line)
        return lines

    # --- DeviceDriver 구현 ---

    async def get_status(self) -> DeviceStatus:
        now = datetime.now(timezone.utc).isoformat()
        try:
            mute_resp = await self._call(cmd.MUTE_NEAR_GET)
            muted = mute_resp == "mute near on"

            call_lines = await self._call_block(cmd.CALLINFO_ALL, "callinfo begin", "callinfo end")
            in_call = bool(call_lines) and call_lines[0] != "system is not in a call"
            call_peer = None
            if in_call:
                parts = call_lines[0].split(":")
                if len(parts) > 2:
                    call_peer = parts[2]

            # 모델명(_fetch_model)과 같은 이유로 개별 보호: uptime 조회 실패가 통화/음소거
            # 등 나머지 상태 조회까지 offline으로 끌어내리지 않게 한다.
            try:
                uptime_resp = await self._call(cmd.UPTIME_GET)
                uptime_seconds = _parse_uptime(uptime_resp)
            except DriverError:
                uptime_seconds = None

            return DeviceStatus(
                online=True,
                in_call=in_call,
                muted=muted,
                call_peer=call_peer,
                last_polled_at=now,
                model=self._model,
                uptime_seconds=uptime_seconds,
            )
        except DriverError as exc:
            return DeviceStatus(
                online=False,
                in_call=False,
                muted=False,
                call_peer=None,
                last_polled_at=now,
                error=str(exc),
                model=self._model,
            )

    async def mute(self, on: bool) -> bool:
        resp = await self._call(cmd.mute_near(on))
        expected = "mute near on" if on else "mute near off"
        return resp == expected

    async def dial(self, address: str) -> bool:
        resp = await self._call(cmd.dial_manual(address))
        return resp.startswith("dialing")

    async def hangup(self) -> bool:
        resp = await self._call(cmd.hangup_video())
        return resp == "hanging up video"

    async def reboot(self) -> bool:
        # 문서: "reboot now"는 확인 없이 재시작하며 별도 피드백을 반환하지 않는다.
        await self._send(cmd.REBOOT_NOW)
        return True

    async def get_calendar_status(self) -> str:
        resp = await self._call(cmd.CALENDARSTATUS_GET)
        if resp == "calendarstatus established":
            return "registered"
        if resp == "calendarstatus unavailable":
            return "not_registered"
        return "error"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        lines = await self._call_block(
            cmd.calendarmeetings_list(), "calendarmeetings list begin", "calendarmeetings list end"
        )
        entries: list[CalendarEntry] = []
        for line in lines:
            if not line.startswith("meeting|"):
                continue
            _, meeting_id, start, end, subject = line.split("|", 4)
            join_uri = await self._fetch_join_uri(meeting_id)
            entries.append(
                CalendarEntry(
                    subject=subject,
                    start_time=_normalize_poly_datetime(start),
                    end_time=_normalize_poly_datetime(end),
                    join_uri=join_uri,
                )
            )
        return entries

    async def _fetch_join_uri(self, meeting_id: str) -> str | None:
        info_lines = await self._call_block(
            cmd.calendarmeetings_info(meeting_id),
            "calendarmeetings info start",
            "calendarmeetings info end",
        )
        for line in info_lines:
            if line.startswith("dialingnumber|"):
                parts = line.split("|")
                if len(parts) >= 3:
                    return parts[2]
        return None

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        if not entry.join_uri:
            raise DriverCommandError("meeting has no dialable join_uri")
        resp = await self._call(cmd.dial_phone(entry.join_uri))
        return resp.startswith("dialing")


def _normalize_poly_datetime(raw: str) -> str:
    """Poly의 "YYYY-MM-DD:HH:MM" 타임스탬프를 Cisco(ISO 8601)와 비교 가능한
    "YYYY-MM-DDTHH:MM:00" 형태로 변환한다.

    두 벤더의 CalendarEntry.start_time/end_time은 JS 쪽에서 문자열 사전순
    비교(오늘 남은 회의 필터링, 정렬)에 그대로 쓰이는 공유 계약이다. Poly는
    날짜/시간 구분자로 ":"(0x3A)를, ISO는 "T"(0x54)를 쓰는데 ":"가 "T"보다
    아스키상 앞이라 Poly 회의는 항상 "이미 지난 회의"로 비교돼버린다 — 그래서
    드라이버 경계에서 정규화해 형태를 맞춘다. Poly는 타임존 오프셋을 보내지
    않으므로 오프셋/Z는 붙이지 않고(naive local-time) 초 단위(:00)만 채운다.
    """
    return raw.replace(":", "T", 1) + ":00"


_UPTIME_UNIT_SECONDS = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}


def _parse_uptime(text: str) -> int | None:
    """Poly "uptime get" 응답("1 Hour, 10 Minutes" 형식)을 초로 환산한다.
    Day 단위 표기가 실제로 포함되는지는 문서에 예시가 없어 미확인 — Day/Hour/Minute/Second를
    느슨하게(대소문자 무관, 단수/복수 무관) 인식하고, 하나도 못 찾으면 None을 반환해
    상위 계층이 원문을 그대로 보여줄 수 있게 한다."""
    total = 0
    found = False
    for match in re.finditer(r"(\d+)\s*(day|hour|minute|second)s?", text, re.IGNORECASE):
        found = True
        value = int(match.group(1))
        unit = match.group(2).lower()
        total += value * _UPTIME_UNIT_SECONDS[unit]
    return total if found else None
