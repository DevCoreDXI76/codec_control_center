# app/drivers/cisco/cisco_driver.py
"""
Cisco RoomOS SSH(xAPI) 드라이버.

paramiko는 동기(블로킹) API이므로, 모든 실제 통신은 동기 헬퍼(_*_sync)에서 수행하고
DeviceDriver 인터페이스의 async 메서드는 asyncio.to_thread로 감싼다.
cisco_commands.py에서 문서 대조로 확정한 명령만 사용한다.
"""
from __future__ import annotations

import asyncio
import re
import socket
from datetime import datetime, timedelta, timezone

import paramiko

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
from . import cisco_commands as cmd

_END_MARKER = "** end"


class CiscoDriver(DeviceDriver):
    def __init__(
        self,
        host: str,
        port: int = 2222,
        username: str = "admin",
        password: str = "",
        timeout: float = 7.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client: paramiko.SSHClient | None = None
        self._channel = None
        self._buffer = b""
        self._model: str | None = None

    async def connect(self) -> None:
        await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> None:
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
        self._client = client
        self._channel = channel
        self._buffer = b""
        self._model = self._fetch_model_sync()

    def _fetch_model_sync(self) -> str | None:
        try:
            lines = self._call_block_sync(cmd.STATUS_SYSTEMUNIT_PRODUCT_ID)
        except DriverError:
            return None
        for line in lines:
            if line.startswith("*s SystemUnit ProductId:"):
                return line.split(":", 1)[-1].strip().strip('"')
        return None

    async def disconnect(self) -> None:
        await asyncio.to_thread(self._disconnect_sync)

    def _disconnect_sync(self) -> None:
        # 연결이 이미 끊어진/불안정한 상태에서도 정리(cleanup)는 항상 조용히 끝나야 한다.
        if self._channel is not None:
            try:
                self._channel.close()
            except (paramiko.SSHException, OSError, EOFError):
                pass
        if self._client is not None:
            try:
                self._client.close()
            except (paramiko.SSHException, OSError, EOFError):
                pass
        self._channel = None
        self._client = None

    # --- 내부 통신 헬퍼 (동기, 스레드 안에서만 호출) ---

    def _read_line_sync(self) -> str:
        if self._channel is None:
            raise DriverConnectionError("not connected")
        while b"\n" not in self._buffer:
            try:
                data = self._channel.recv(4096)
            except socket.timeout as exc:
                raise DriverTimeoutError("timeout waiting for device response") from exc
            except OSError as exc:
                raise DriverConnectionError(str(exc)) from exc
            if not data:
                raise DriverConnectionError("connection closed by device")
            self._buffer += data
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.decode("utf-8", errors="replace").strip()

    def _call_block_sync(self, command: str, end: str = _END_MARKER) -> list[str]:
        if self._channel is None:
            raise DriverConnectionError("not connected")
        try:
            self._channel.send(command + "\n")
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc
        lines: list[str] = []
        while True:
            line = self._read_line_sync()
            if line == end:
                break
            lines.append(line)
        return lines

    # --- DeviceDriver 구현 ---

    async def get_status(self) -> DeviceStatus:
        now = datetime.now(timezone.utc).isoformat()
        try:
            return await asyncio.to_thread(self._get_status_sync, now)
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

    def _get_status_sync(self, now: str) -> DeviceStatus:
        mute_lines = self._call_block_sync(cmd.STATUS_AUDIO_MUTE)
        muted = any(line.rsplit(":", 1)[-1].strip() == "On" for line in mute_lines if "Audio Microphones Mute:" in line)

        call_lines = self._call_block_sync(cmd.STATUS_CALL)
        in_call = any(line.startswith("*s Call ") for line in call_lines)
        call_peer = None
        for line in call_lines:
            if "RemoteNumber:" in line:
                call_peer = line.split("RemoteNumber:", 1)[-1].strip().strip('"')
                break

        # uptime 조회는 별도로 보호한다: Poly 드라이버에서 발견된 것과 같은 문제
        # (uptime get 실패가 get_status() 전체를 offline으로 끌어내림)를 막기 위해,
        # 이 호출 자체의 DriverError(타임아웃/미지원 명령 등)를 mute/call 상태
        # 조회와 분리해서 흡수한다.
        try:
            uptime_lines = self._call_block_sync(cmd.STATUS_SYSTEMUNIT_UPTIME)
        except DriverError:
            uptime_lines = []
        uptime_seconds = None
        for line in uptime_lines:
            if line.startswith("*s SystemUnit Uptime:"):
                try:
                    uptime_seconds = int(line.split(":", 1)[-1].strip())
                except ValueError:
                    uptime_seconds = None
                break

        return DeviceStatus(
            online=True,
            in_call=in_call,
            muted=muted,
            call_peer=call_peer,
            last_polled_at=now,
            model=self._model,
            uptime_seconds=uptime_seconds,
        )

    async def mute(self, on: bool) -> bool:
        return await asyncio.to_thread(self._mute_sync, on)

    def _mute_sync(self, on: bool) -> bool:
        command = cmd.AUDIO_MUTE if on else cmd.AUDIO_UNMUTE
        # 확인됨(2026-07-31 VDI 실장비 응답 원문): 결과 라인은 "*r MicrophonesMuteResult"/
        # "*r MicrophonesUnmuteResult"이다 — 다른 Audio Microphones 명령들과 달리 "Audio"가
        # 빠진다. 예전 값("*r AudioMicrophonesMuteResult")은 어느 명령과도 안 맞아 mute/unmute가
        # 실장비에서 항상 실패로 기록되던 버그였다.
        expected = "*r MicrophonesMuteResult" if on else "*r MicrophonesUnmuteResult"
        lines = self._call_block_sync(command)
        return _check_result_ok(lines, expected)

    async def dial(self, address: str) -> bool:
        return await asyncio.to_thread(self._dial_sync, address)

    def _dial_sync(self, address: str) -> bool:
        lines = self._call_block_sync(cmd.dial(address))
        return _check_result_ok(lines, "*r DialResult")

    async def hangup(self) -> bool:
        return await asyncio.to_thread(self._hangup_sync)

    def _hangup_sync(self) -> bool:
        lines = self._call_block_sync(cmd.CALL_DISCONNECT)
        return _check_result_ok(lines, "*r CallDisconnectResult")

    async def reboot(self) -> bool:
        return await asyncio.to_thread(self._reboot_sync)

    def _reboot_sync(self) -> bool:
        # 문서/레퍼런스 드라이버 모두 재부팅 명령에 대한 피드백 형식을 확정하지 않았고,
        # 실제로도 재부팅 시 세션이 끊기는 것이 일반적이므로 응답을 기다리지 않는다
        # (Poly reboot과 동일한 설계 원칙).
        if self._channel is None:
            raise DriverConnectionError("not connected")
        try:
            self._channel.send(cmd.SYSTEMUNIT_BOOT_RESTART + "\n")
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc
        return True

    async def get_calendar_status(self) -> str:
        return await asyncio.to_thread(self._get_calendar_status_sync)

    def _get_calendar_status_sync(self) -> str:
        # 확인됨(RoomOS 11 API Reference Guide p.386): xStatus Bookings Availability Status는
        # Free/FreeUntil/BookedUntil 중 하나를 항상 반환한다. Poly의 "Exchange 등록 여부"와는
        # 개념이 다르지만(예약 기능 자체가 응답 가능한 상태인지), 값이 오면 예약 기능이
        # 정상 동작 중이라는 뜻이므로 "registered"로 매핑한다.
        lines = self._call_block_sync(cmd.STATUS_BOOKINGS_AVAILABILITY)
        for line in lines:
            if line.startswith("*s Bookings Availability Status:"):
                return "registered"
        return "error"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        return await asyncio.to_thread(self._get_obtp_entries_sync)

    def _get_obtp_entries_sync(self) -> list[CalendarEntry]:
        # 확인됨(2026-07-31 VDI 실장비 응답 원문): Bookings List 결과의 모든 줄에
        # "*r BookingsListResult " 프리픽스가 붙고(다른 xCommand 결과와 동일한 RoomOS
        # 컨벤션), Title/Time/DialInfo까지 이미 다 포함돼 있어 회의별 Bookings Get을
        # 따로 호출할 필요가 없다 — 기존 파서는 이 프리픽스를 고려하지 않아 모든 줄을
        # 건너뛰는 바람에 일정이 하나도 안 잡히던 버그였다.
        list_lines = self._call_block_sync(cmd.bookings_list())
        return _parse_bookings_list(list_lines)

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        if not entry.join_uri:
            raise DriverCommandError("meeting has no dialable join_uri")
        return await self.dial(entry.join_uri)


def _check_result_ok(lines: list[str], expected_prefix: str) -> bool:
    """명령 결과 라인이 status=OK인지 확인한다.

    RoomOS 문서는 성공 응답 형식(``*r <Command>Result (status=OK): ... ** end``)만
    확정되어 있고, 권한 부족/미지원 명령 등 실패 시 정확한 오류 코드 체계는 문서에
    없다. 대신 실패를 조용히 False로 삼키지 않고, 장비가 실제로 보낸 응답 원문을
    DriverCommandError에 담아 올린다 — 그래야 /logs·UI 토스트에서 "왜" 실패했는지
    확인할 수 있다 (권한 부족, 모델 미지원 명령 등 실제 원인은 이 원문에서 드러난다).
    """
    for line in lines:
        if line.startswith(expected_prefix):
            if "status=OK" in line:
                return True
            raise DriverCommandError(f"device rejected command: {line}")
    if lines:
        raise DriverCommandError(f"unexpected response: {lines}")
    raise DriverCommandError("empty response from device")


_BOOKINGS_LIST_PREFIX = "*r BookingsListResult "
_BOOKING_FIELD_RE = re.compile(r"^Booking (\d+) (.+)$")

_KST = timezone(timedelta(hours=9))
"""한국 표준시(UTC+9, 서머타임 없음) 고정 오프셋. Windows 실행 환경(PyInstaller onefile)에는
tzdata 패키지가 없어 zoneinfo("Asia/Seoul")를 쓰면 ZoneInfoNotFoundError가 난다
(app/core/history.py의 _to_kst_display와 동일한 이유) — 한국은 DST가 없으므로 고정
오프셋으로 충분하다."""


def _cisco_utc_to_kst_naive(raw: str) -> str:
    """Cisco Bookings List/Get의 시간 필드는 UTC ISO 8601("...Z" 접미사)로 온다(2026-07-31
    VDI 실장비 원문으로 확인 — 예: "2026-07-31T04:30:00Z"). 그대로 화면에 표시하면 실제
    한국시간보다 9시간 이른 값으로 보인다(예: 실제 13:30 KST 회의가 04:30로 표시됨 —
    2026-08-03 VDI 재테스트에서 지적됨). Poly(_normalize_poly_datetime)는 오프셋 없는
    naive KST 문자열을 만들므로, 프런트엔드가 두 벤더를 동일하게 다룰 수 있도록 여기서도
    UTC→KST 변환 후 naive 문자열로 맞춘다. 파싱 실패(형식이 예상과 다름) 시 원문을 그대로
    반환한다 — 잘못된 시간이라도 표시가 아예 사라지는 것보다는 원인 파악이 쉽다."""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return parsed.astimezone(_KST).replace(tzinfo=None).isoformat()


def _parse_bookings_list(list_lines: list[str]) -> list[CalendarEntry]:
    """"*r BookingsListResult Booking <n> <필드경로>: "<값>"" 형태의 줄들을
    회의별로 묶어 CalendarEntry로 변환한다 (2026-07-31 VDI 실장비 응답 원문으로 확인)."""
    bookings: dict[str, dict[str, str]] = {}
    for raw in list_lines:
        line = raw.strip()
        if line.startswith(_BOOKINGS_LIST_PREFIX):
            line = line[len(_BOOKINGS_LIST_PREFIX) :]
        match = _BOOKING_FIELD_RE.match(line)
        if not match:
            continue
        index, rest = match.group(1), match.group(2)
        key, sep, value = rest.partition(": ")
        if not sep:
            continue
        bookings.setdefault(index, {})[key] = value.strip('"')

    entries: list[CalendarEntry] = []
    for fields in bookings.values():
        if "Title" not in fields:
            continue
        entries.append(
            CalendarEntry(
                subject=fields.get("Title", ""),
                start_time=_cisco_utc_to_kst_naive(fields.get("Time StartTime", "")),
                end_time=_cisco_utc_to_kst_naive(fields.get("Time EndTime", "")),
                join_uri=fields.get("DialInfo Calls Call 1 Number"),
            )
        )
    return entries
