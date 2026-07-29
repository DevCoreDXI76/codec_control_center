import asyncio
import logging

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
    await scheduler.add_device("dev-1")
    status = await scheduler.poll_once("dev-1")
    assert status.online is True
    assert scheduler.get_status("dev-1") is status


async def test_poll_once_unknown_device_raises_keyerror(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory)
    with pytest.raises(KeyError):
        await scheduler.poll_once("no-such-device")


async def test_session_reused_across_polls(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=15.0)
    await scheduler.add_device("dev-1")
    await scheduler.poll_once("dev-1")
    await scheduler.poll_once("dev-1")
    assert registry.created["dev-1"].connect_calls == 1  # 재접속하지 않고 세션 재사용


async def test_connect_failure_marks_offline_and_backs_off(registry):
    registry.connect_should_fail["dev-1"] = True
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=10.0, max_interval=100.0)
    await scheduler.add_device("dev-1", interval=10.0)

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
    await scheduler.add_device("dev-1", interval=10.0)

    for _ in range(5):
        await scheduler.poll_once("dev-1")

    assert scheduler._runtimes["dev-1"].interval == 25.0


async def test_recovery_resets_interval_and_failure_count(registry):
    registry.connect_should_fail["dev-1"] = True
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=10.0, max_interval=100.0)
    await scheduler.add_device("dev-1", interval=10.0)

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
        await scheduler.add_device(device_id)

    await asyncio.gather(*(scheduler.poll_once(device_id) for device_id in device_ids))
    assert registry.max_concurrent <= 2


async def test_update_concurrency_changes_semaphore_limit(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=15.0, max_concurrency=1)
    scheduler.update_concurrency(5)
    assert scheduler.max_concurrency == 5

    device_ids = [f"dev-{i}" for i in range(6)]
    for device_id in device_ids:
        await scheduler.add_device(device_id)
    await asyncio.gather(*(scheduler.poll_once(device_id) for device_id in device_ids))
    assert registry.max_concurrent <= 5


async def test_start_and_stop_lifecycle_disconnects_drivers(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=0.05)
    await scheduler.add_device("dev-1")
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
    await scheduler.add_device("dev-1")
    await scheduler.poll_once("dev-1")
    assert len(received) == 1
    assert received[0][0] == "dev-1"


async def test_add_device_while_running_spawns_polling_task(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=0.05)
    await scheduler.start()
    try:
        await scheduler.add_device("dev-late")
        await asyncio.sleep(0.12)
        assert registry.created["dev-late"].connect_calls >= 1
    finally:
        await scheduler.stop()


async def test_add_device_while_running_does_not_poll_immediately(registry):
    """등록 직후 바로 접속을 시도하지 않고 한 폴링 주기(interval)를 기다린 뒤 첫 폴링을 한다
    (Phase③ 실장비 검증: 준비 안 된 장비를 등록하자마자 오류로 표시되는 문제 방지)."""
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=1.0)
    await scheduler.start()
    try:
        await scheduler.add_device("dev-late")
        await asyncio.sleep(0.05)
        assert "dev-late" not in registry.created
        assert scheduler.get_status("dev-late") is None
    finally:
        await scheduler.stop()


async def test_get_driver_reuses_same_session(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=15.0)
    await scheduler.add_device("dev-1")
    driver1 = await scheduler.get_driver("dev-1")
    driver2 = await scheduler.get_driver("dev-1")
    assert driver1 is driver2
    assert registry.created["dev-1"].connect_calls == 1


async def test_get_driver_unknown_device_raises_keyerror(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory)
    with pytest.raises(KeyError):
        await scheduler.get_driver("no-such-device")


async def test_reset_device_disconnects_and_clears_session(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory, base_interval=15.0)
    await scheduler.add_device("dev-1")
    driver1 = await scheduler.get_driver("dev-1")

    await scheduler.reset_device("dev-1")
    assert driver1.disconnect_calls == 1

    driver2 = await scheduler.get_driver("dev-1")
    assert driver2 is not driver1
    assert driver2.connect_calls == 1


async def test_reset_device_unknown_or_no_session_is_noop(registry):
    scheduler = PollingScheduler(driver_factory=registry.factory)
    await scheduler.reset_device("no-such-device")  # 예외 없이 무시
    await scheduler.add_device("dev-1")
    await scheduler.reset_device("dev-1")  # 아직 연결 안 된 상태도 무시


class _BoomDriver(DeviceDriver):
    """DriverError가 아닌 예상 밖 예외(버그)를 흉내내는 테스트 전용 드라이버."""

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_status(self) -> DeviceStatus:
        raise RuntimeError("boom")

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


async def test_unexpected_exception_marked_offline_not_raised(caplog):
    """DriverError가 아닌 버그성 예외도 삼키지 않고 로그로 남기되, 폴링 루프 자체는
    죽지 않고 오프라인 상태로 계속 재시도해야 한다."""
    scheduler = PollingScheduler(driver_factory=lambda device_id: _BoomDriver(), base_interval=15.0)
    await scheduler.add_device("dev-1")
    with caplog.at_level(logging.ERROR, logger="app.core.polling"):
        status = await scheduler.poll_once("dev-1")
    assert status.online is False
    assert "unexpected error" in status.error
    assert any("unexpected error" in record.message for record in caplog.records)


async def test_poll_failure_logs_device_label_not_raw_id(registry, caplog):
    registry.connect_should_fail["dev-1"] = True
    scheduler = PollingScheduler(
        driver_factory=registry.factory,
        base_interval=10.0,
        get_device_label=lambda device_id: "3층 대회의실",
    )
    await scheduler.add_device("dev-1")
    with caplog.at_level(logging.WARNING, logger="app.core.polling"):
        await scheduler.poll_once("dev-1")
    assert any("3층 대회의실" in record.message for record in caplog.records)
