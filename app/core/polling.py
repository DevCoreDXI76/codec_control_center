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
        get_device_label: Callable[[str], str] | None = None,
    ) -> None:
        """get_device_label은 로그에 device_id 대신 사람이 알아볼 수 있는 이름을
        남기기 위한 조회 함수다 (미지정 시 device_id를 그대로 쓴다)."""
        self._driver_factory = driver_factory
        self.base_interval = base_interval
        self.max_interval = max_interval
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._on_status = on_status
        self._get_device_label = get_device_label or (lambda device_id: device_id)
        self._runtimes: dict[str, _DeviceRuntime] = {}
        self._running = False

    def update_concurrency(self, max_concurrency: int) -> None:
        """설정 변경 시 동시 접속 제한을 갱신한다 (다음 폴링부터 적용)."""
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def add_device(self, device_id: str, interval: float | None = None) -> None:
        """장비를 스케줄러에 등록한다.

        이미 폴링 중(running)이면 등록 즉시 접속을 시도하지 않고, 한 폴링 주기가
        지난 뒤 첫 폴링을 수행한다 — 등록 직후 아직 준비되지 않은 장비(예: SSH
        설정이 안 끝난 실장비)에 곧바로 접속을 시도해 오류로 표시되는 것을 피하기
        위함 (Phase③ 실장비 검증에서 확인된 문제).
        """
        runtime = _DeviceRuntime(interval=interval or self.base_interval)
        self._runtimes[device_id] = runtime
        if self._running:
            runtime.task = asyncio.create_task(self._poll_loop(device_id, delay_first_poll=True))

    def remove_device(self, device_id: str) -> None:
        runtime = self._runtimes.pop(device_id, None)
        if runtime is not None and runtime.task is not None:
            runtime.task.cancel()

    def get_status(self, device_id: str) -> DeviceStatus | None:
        runtime = self._runtimes.get(device_id)
        return runtime.last_status if runtime else None

    async def reset_device(self, device_id: str) -> None:
        """장비 접속 정보/자격증명이 바뀌었을 때 기존 세션을 끊어 다음 폴링에서 재연결하게 한다."""
        runtime = self._runtimes.get(device_id)
        if runtime is None or runtime.driver is None:
            return
        try:
            await runtime.driver.disconnect()
        except DriverError:
            pass
        runtime.driver = None

    async def get_driver(self, device_id: str) -> DeviceDriver:
        """제어 API 등에서 폴링과 동일한(재사용되는) 드라이버 세션을 얻는다."""
        runtime = self._runtimes.get(device_id)
        if runtime is None:
            raise KeyError(f"unknown device id: {device_id}")
        async with self._semaphore:
            if runtime.driver is None:
                runtime.driver = self._driver_factory(device_id)
                await runtime.driver.connect()
        return runtime.driver

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

    async def _poll_loop(self, device_id: str, delay_first_poll: bool = False) -> None:
        runtime = self._runtimes[device_id]
        if delay_first_poll:
            await asyncio.sleep(runtime.interval)
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
            logger.warning("device %s poll failed: %s", self._get_device_label(device_id), exc)
            status = DeviceStatus(
                online=False,
                in_call=False,
                muted=False,
                call_peer=None,
                last_polled_at=_now_iso(),
                error=str(exc),
            )
            runtime.driver = None  # 다음 폴링에서 재연결 시도 (세션이 끊겼을 가능성)
        except Exception as exc:
            # DriverError가 아닌 예상 밖 예외 — 삼키지 않고 트레이스백까지 남긴다.
            # 여기서 재발생시키면 폴링 루프 태스크 자체가 조용히 죽어버리므로
            # (asyncio는 미처리 태스크 예외를 stderr에만 남기고 계속 진행하지 않는다),
            # 다른 DriverError와 동일하게 오프라인 상태로 처리하고 다음 주기에 재시도한다.
            logger.exception(
                "device %s poll raised unexpected error", self._get_device_label(device_id)
            )
            status = DeviceStatus(
                online=False,
                in_call=False,
                muted=False,
                call_peer=None,
                last_polled_at=_now_iso(),
                error=f"unexpected error: {exc}",
            )
            runtime.driver = None

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
