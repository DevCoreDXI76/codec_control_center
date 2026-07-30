# app/core/driver_base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ConnectionType(str, Enum):
    SSH = "ssh"
    TELNET = "telnet"


@dataclass
class DeviceStatus:
    online: bool
    in_call: bool
    muted: bool
    call_peer: str | None
    last_polled_at: str
    error: str | None = None
    model: str | None = None
    uptime_seconds: int | None = None


@dataclass
class CalendarEntry:
    subject: str
    start_time: str
    end_time: str
    join_uri: str | None  # SIP/CVI 발신 주소 등


class DriverError(Exception):
    """드라이버 계층 공통 예외."""


class DriverConnectionError(DriverError):
    """연결 실패."""


class DriverAuthError(DriverError):
    """인증 실패."""


class DriverCommandError(DriverError):
    """명령 실행 실패."""


class DriverTimeoutError(DriverError):
    """명령/연결 타임아웃."""


class DeviceDriver(ABC):
    """모든 제조사 드라이버가 구현해야 하는 공통 인터페이스."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def get_status(self) -> DeviceStatus: ...

    @abstractmethod
    async def mute(self, on: bool) -> bool: ...

    @abstractmethod
    async def dial(self, address: str) -> bool: ...

    @abstractmethod
    async def hangup(self) -> bool: ...

    @abstractmethod
    async def reboot(self) -> bool: ...

    @abstractmethod
    async def get_calendar_status(self) -> str:
        """캘린더(Teams) 등록 상태: registered / not_registered / error"""
        ...

    @abstractmethod
    async def get_obtp_entries(self) -> list[CalendarEntry]:
        """예정된 회의(OBTP) 목록 조회."""
        ...

    @abstractmethod
    async def join_meeting(self, entry: CalendarEntry) -> bool:
        """SIP/CVI 주소 발신 또는 장비 자체 Join 명령으로 참가."""
        ...
