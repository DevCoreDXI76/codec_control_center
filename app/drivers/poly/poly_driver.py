# app/drivers/poly/poly_driver.py
"""
Poly (Polycom RealPresence Group Series) Telnet API 드라이버.

poly_commands.py에서 문서 대조로 확정한 명령만 사용한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import telnetlib3

from app.core.driver_base import (
    CalendarEntry,
    DeviceDriver,
    DeviceStatus,
    DriverCommandError,
    DriverConnectionError,
    DriverError,
    DriverTimeoutError,
)
from . import poly_commands as cmd


class PolyDriver(DeviceDriver):
    def __init__(self, host: str, port: int = 2323, timeout: float = 7.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader = None
        self._writer = None

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                telnetlib3.open_connection(self.host, self.port), timeout=self.timeout
            )
        except asyncio.TimeoutError as exc:
            raise DriverTimeoutError(f"connect timeout: {self.host}:{self.port}") from exc
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc

    async def disconnect(self) -> None:
        if self._writer is not None:
            self._writer.close()
        self._reader = None
        self._writer = None

    # --- 내부 통신 헬퍼 ---

    async def _read_line(self) -> str:
        if self._reader is None:
            raise DriverConnectionError("not connected")
        try:
            line = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise DriverTimeoutError("timeout waiting for device response") from exc
        if not line:
            raise DriverConnectionError("connection closed by device")
        return line.strip()

    async def _call(self, command: str) -> str:
        if self._writer is None:
            raise DriverConnectionError("not connected")
        try:
            self._writer.write(command + "\r\n")
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc
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

            return DeviceStatus(
                online=True,
                in_call=in_call,
                muted=muted,
                call_peer=call_peer,
                last_polled_at=now,
            )
        except DriverError as exc:
            return DeviceStatus(
                online=False,
                in_call=False,
                muted=False,
                call_peer=None,
                last_polled_at=now,
                error=str(exc),
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
        if self._writer is None:
            raise DriverConnectionError("not connected")
        try:
            self._writer.write(cmd.REBOOT_NOW + "\r\n")
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc
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
            entries.append(CalendarEntry(subject=subject, start_time=start, end_time=end, join_uri=join_uri))
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
