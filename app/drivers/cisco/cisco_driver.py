# app/drivers/cisco/cisco_driver.py
"""
Cisco RoomOS SSH(xAPI) 드라이버.

paramiko는 동기(블로킹) API이므로, 모든 실제 통신은 동기 헬퍼(_*_sync)에서 수행하고
DeviceDriver 인터페이스의 async 메서드는 asyncio.to_thread로 감싼다.
cisco_commands.py에서 문서 대조로 확정한 명령만 사용한다.
"""
from __future__ import annotations

import asyncio
import socket
from datetime import datetime, timezone

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

        return DeviceStatus(online=True, in_call=in_call, muted=muted, call_peer=call_peer, last_polled_at=now)

    async def mute(self, on: bool) -> bool:
        return await asyncio.to_thread(self._mute_sync, on)

    def _mute_sync(self, on: bool) -> bool:
        command = cmd.AUDIO_MUTE if on else cmd.AUDIO_UNMUTE
        expected = "*r AudioMicrophonesMuteResult" if on else "*r AudioMicrophonesUnmuteResult"
        lines = self._call_block_sync(command)
        return any(line.startswith(expected) and "status=OK" in line for line in lines)

    async def dial(self, address: str) -> bool:
        return await asyncio.to_thread(self._dial_sync, address)

    def _dial_sync(self, address: str) -> bool:
        lines = self._call_block_sync(cmd.dial(address))
        return any(line.startswith("*r DialResult") and "status=OK" in line for line in lines)

    async def hangup(self) -> bool:
        return await asyncio.to_thread(self._hangup_sync)

    def _hangup_sync(self) -> bool:
        lines = self._call_block_sync(cmd.CALL_DISCONNECT)
        return any(line.startswith("*r CallDisconnectResult") and "status=OK" in line for line in lines)

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
        # Cisco Bookings API 응답 스키마 미확인 (대상 모델 미확정 — PRD 오픈 이슈).
        # 추측 구현 대신 명시적으로 미구현 처리 — Phase④에서 모델 확정 후 문서 재확인.
        raise NotImplementedError(
            "Cisco 캘린더 상태 조회는 대상 모델 확정 및 Bookings API 문서 재확인 후 구현 예정 (Phase④)"
        )

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        raise NotImplementedError(
            "Cisco Bookings List 응답 스키마 미확인 — 대상 모델 확정 후 구현 예정 (Phase④)"
        )

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        if not entry.join_uri:
            raise DriverCommandError("meeting has no dialable join_uri")
        return await self.dial(entry.join_uri)
