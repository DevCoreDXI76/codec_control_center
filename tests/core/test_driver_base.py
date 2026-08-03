import pytest

from app.core.driver_base import (
    CalendarEntry,
    ConnectionType,
    DeviceDriver,
    DeviceStatus,
    DriverError,
    DriverConnectionError,
)


class _FakeDriver(DeviceDriver):
    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_status(self) -> DeviceStatus:
        return DeviceStatus(
            online=True,
            in_call=False,
            muted=False,
            call_peer=None,
            last_polled_at="2026-07-28T00:00:00",
        )

    async def mute(self, on: bool) -> bool:
        return True

    async def dial(self, address: str) -> bool:
        return True

    async def hangup(self) -> bool:
        return True

    async def reboot(self) -> bool:
        return True

    async def get_calendar_status(self) -> str:
        return "registered"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        return []

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        return True


def test_device_driver_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        DeviceDriver()  # type: ignore[abstract]


def test_incomplete_subclass_cannot_be_instantiated():
    class _Incomplete(DeviceDriver):
        async def connect(self) -> None:
            pass

    with pytest.raises(TypeError):
        _Incomplete()  # type: ignore[abstract]


async def test_fake_driver_implements_full_lifecycle():
    driver = _FakeDriver()
    await driver.connect()
    status = await driver.get_status()
    assert status.online is True
    assert status.error is None
    assert await driver.mute(True) is True
    assert await driver.dial("1234") is True
    assert await driver.hangup() is True
    assert await driver.reboot() is True
    assert await driver.get_calendar_status() == "registered"
    assert await driver.get_obtp_entries() == []
    await driver.disconnect()


def test_connection_type_values():
    assert ConnectionType.SSH == "ssh"
    assert ConnectionType.TELNET == "telnet"


def test_calendar_entry_fields():
    entry = CalendarEntry(
        subject="주간회의",
        start_time="2026-07-28T14:00:00",
        end_time="2026-07-28T15:00:00",
        join_uri="sip:1234@example.com",
    )
    assert entry.subject == "주간회의"
    assert entry.join_uri == "sip:1234@example.com"


def test_driver_error_hierarchy():
    assert issubclass(DriverConnectionError, DriverError)


def test_driver_conflict_error_is_a_driver_error():
    from app.core.driver_base import DriverConflictError

    assert issubclass(DriverConflictError, DriverError)


def test_device_status_model_and_uptime_default_to_none():
    status = DeviceStatus(online=True, in_call=False, muted=False, call_peer=None, last_polled_at="now")
    assert status.model is None
    assert status.uptime_seconds is None


def test_device_status_accepts_model_and_uptime():
    status = DeviceStatus(
        online=True, in_call=False, muted=False, call_peer=None, last_polled_at="now",
        model="RealPresence Group 700", uptime_seconds=3660,
    )
    assert status.model == "RealPresence Group 700"
    assert status.uptime_seconds == 3660
