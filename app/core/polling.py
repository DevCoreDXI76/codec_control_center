# app/core/polling.py
"""
asyncio 기반 병렬 폴링 스케줄러 (SPEC.md 8절).

- Semaphore로 동시 접속 수를 제한한다 (보안 장비 오탐 방지).
- 장비별 드라이버 연결(세션)은 재사용하고, 폴링마다 새로 접속하지 않는다.
- 연속 실패 장비는 폴링 주기를 지수적으로 늘린다(예: 15s -> 30s -> 60s -> ...).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.driver_base import DeviceDriver, DeviceStatus, DriverError

logger = logging.getLogger(__name__)

DriverFactory = Callable[[str], DeviceDriver]
StatusCallback = Callable[[str, DeviceStatus], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _DeviceRuntime:
    interval: float
    driver: DeviceDriver | None = None
    consecutive_failures: int = 0
    last_status: DeviceStatus | None = None
    task: asyncio.Task | None = None


class PollingScheduler:
    def __init__(
        self,
        *,
        driver_factory: DriverFactory,
        base_interval: float = 15.0,
        max_interval: float = 120.0,
        max_concurrency: int = 8,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._driver_factory = driver_factory
        self.base_interval = base_interval
        self.max_interval = max_interval
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._on_status = on_status
        self._runtimes: dict[str, _DeviceRuntime] = {}
        self._running = False

    def add_device(self, device_id: str, interval: float | None = None) -> None:
        self._runtimes[device_id] = _DeviceRuntime(interval=interval or self.base_interval)

    def remove_device(self, device_id: str) -> None:
        runtime = self._runtimes.pop(device_id, None)
        if runtime is not None and runtime.task is not None:
            runtime.task.cancel()

    def get_status(self, device_id: str) -> DeviceStatus | None:
        runtime = self._runtimes.get(device_id)
        return runtime.last_status if runtime else None

    async def start(self) -> None:
        self._running = True
        for device_id, runtime in self._runtimes.items():
            if runtime.task is None:
                runtime.task = asyncio.create_task(self._poll_loop(device_id))

    async def stop(self) -> None:
        self._running = False
        tasks = [r.task for r in self._runtimes.values() if r.task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        for runtime in self._runtimes.values():
            runtime.task = None
            if runtime.driver is not None:
                try:
                    await runtime.driver.disconnect()
                except DriverError:
                    pass
                runtime.driver = None

    async def poll_once(self, device_id: str) -> DeviceStatus:
        """단일 장비를 즉시 1회 폴링한다 (수동 새로고침 등에서 사용)."""
        runtime = self._runtimes.get(device_id)
        if runtime is None:
            raise KeyError(f"unknown device id: {device_id}")
        async with self._semaphore:
            return await self._poll_device(device_id, runtime)

    async def _poll_loop(self, device_id: str) -> None:
        runtime = self._runtimes[device_id]
        while self._running:
            async with self._semaphore:
                await self._poll_device(device_id, runtime)
            await asyncio.sleep(runtime.interval)

    async def _poll_device(self, device_id: str, runtime: _DeviceRuntime) -> DeviceStatus:
        try:
            if runtime.driver is None:
                runtime.driver = self._driver_factory(device_id)
                await runtime.driver.connect()
            status = await runtime.driver.get_status()
        except DriverError as exc:
            status = DeviceStatus(
                online=False,
                in_call=False,
                muted=False,
                call_peer=None,
                last_polled_at=_now_iso(),
                error=str(exc),
            )
            runtime.driver = None  # 다음 폴링에서 재연결 시도 (세션이 끊겼을 가능성)

        if status.online:
            runtime.consecutive_failures = 0
            runtime.interval = self.base_interval
        else:
            runtime.consecutive_failures += 1
            runtime.interval = min(
                self.base_interval * (2**runtime.consecutive_failures), self.max_interval
            )

        runtime.last_status = status
        if self._on_status is not None:
            self._on_status(device_id, status)
        return status
