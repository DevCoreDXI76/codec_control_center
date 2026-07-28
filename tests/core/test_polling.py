import asyncio

import pytest

from app.core.driver_base import (
    CalendarEntry,
    DeviceDriver,
    DeviceStatus,
    DriverConnectionError,
)
from app.core.polling import PollingScheduler


class FakeDriver(DeviceDriver):
    """테스트 전용: connect 성공/실패, get_status 결과를 마음대로 제어."""

    def __init__(self, device_id: str, registry: "FakeDriverRegistry") -> None:
        self.device_id = device_id
        self._registry = registry
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self.connect_calls += 1
        if self._registry.connect_should_fail.get(self.device_id):
            raise DriverConnectionError("simulated connect failure")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1

    async def get_status(self) -> DeviceStatus:
        self._registry.concurrent_calls += 1
        self._registry.max_concurrent = max(self._registry.max_concurrent, self._registry.concurrent_calls)
        await asyncio.sleep(0.01)
        self._registry.concurrent_calls -= 1
        return self._registry.status_for(self.device_id)

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


class FakeDriverRegistry:
    def __init__(self) -> None:
        self.connect_should_fail: dict[str, bool] = {}
        self.concurrent_calls = 0
        self.max_concurrent = 0
        self.created: dict[str, FakeDriver] = {}

    def factory(self, device_id: str) -> FakeDriver:
        driver = FakeDriver(device_id, self)
        self.created[device_id] = driver
        return driver

    def status_for(self, device_id: str) -> DeviceStatus:
        return DeviceStatus(
            online=True, in_call=False, muted=False, call_peer=None, last_polled_at="now"
        )


@pytest.fixture
def registry():
    return FakeDriverRegistry()


async def test_poll_once_returns_online_status(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=15.0)
    scheduler.add_device("dev-1")
    status = await scheduler.poll_once("dev-1")
    assert status.online is True
    assert scheduler.get_status("dev-1") is status


async def test_poll_once_unknown_device_raises_keyerror(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory)
    with pytest.raises(KeyError):
        await scheduler.poll_once("no-such-device")


async def test_session_reused_across_polls(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=15.0)
    scheduler.add_device("dev-1")
    await scheduler.poll_once("dev-1")
    await scheduler.poll_once("dev-1")
    assert registry.created["dev-1"].connect_calls == 1  # 재접속하지 않고 세션 재사용


async def test_connect_failure_marks_offline_and_backs_off(registry):
    registry.connect_should_fail["dev-1"] = True
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=10.0, max_interval=100.0)
    scheduler.add_device("dev-1", interval=10.0)

    status1 = await scheduler.poll_once("dev-1")
    assert status1.online is False
    assert status1.error is not None
    runtime_interval_1 = scheduler._runtimes["dev-1"].interval
    assert runtime_interval_1 == 20.0  # 10 * 2^1

    status2 = await scheduler.poll_once("dev-1")
    assert status2.online is False
    runtime_interval_2 = scheduler._runtimes["dev-1"].interval
    assert runtime_interval_2 == 40.0  # 10 * 2^2


async def test_backoff_capped_at_max_interval(registry):
    registry.connect_should_fail["dev-1"] = True
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=10.0, max_interval=25.0)
    scheduler.add_device("dev-1", interval=10.0)

    for _ in range(5):
        await scheduler.poll_once("dev-1")

    assert scheduler._runtimes["dev-1"].interval == 25.0


async def test_recovery_resets_interval_and_failure_count(registry):
    registry.connect_should_fail["dev-1"] = True
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=10.0, max_interval=100.0)
    scheduler.add_device("dev-1", interval=10.0)

    await scheduler.poll_once("dev-1")
    await scheduler.poll_once("dev-1")
    assert scheduler._runtimes["dev-1"].interval > 10.0

    registry.connect_should_fail["dev-1"] = False
    status = await scheduler.poll_once("dev-1")
    assert status.online is True
    assert scheduler._runtimes["dev-1"].interval == 10.0
    assert scheduler._runtimes["dev-1"].consecutive_failures == 0


async def test_semaphore_limits_concurrency(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=15.0, max_concurrency=2)
    device_ids = [f"dev-{i}" for i in range(6)]
    for device_id in device_ids:
        scheduler.add_device(device_id)

    await asyncio.gather(*(scheduler.poll_once(device_id) for device_id in device_ids))
    assert registry.max_concurrent <= 2


async def test_start_and_stop_lifecycle_disconnects_drivers(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=0.05)
    scheduler.add_device("dev-1")
    await scheduler.start()
    await asyncio.sleep(0.12)  # 최소 1회 이상 폴링되도록 대기
    await scheduler.stop()

    assert registry.created["dev-1"].connect_calls >= 1
    assert registry.created["dev-1"].disconnect_calls == 1
    assert scheduler.get_status("dev-1") is not None


async def test_on_status_callback_invoked(registry):
    received: list[tuple[str, DeviceStatus]] = []
    scheduler = PollingScheduler(
        driver_factory=registry.factory, base_interval=15.0, on_status=lambda did, s: received.append((did, s))
    )
    scheduler.add_device("dev-1")
    await scheduler.poll_once("dev-1")
    assert len(received) == 1
    assert received[0][0] == "dev-1"
