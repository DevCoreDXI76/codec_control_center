# app/api/ws_status.py
"""WebSocket 상태 브로드캐스트 (/ws/status, SPEC.md 1절/7절)."""
from __future__ import annotations

import asyncio
import dataclasses
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.driver_base import DeviceStatus

router = APIRouter()


class StatusBroadcaster:
    """연결된 WebSocket 클라이언트 전체에게 장비 상태 변경을 push한다."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    def notify(self, device_id: str, status: DeviceStatus) -> None:
        """PollingScheduler의 on_status 콜백(동기)에서 호출 -> 비동기 브로드캐스트를 예약한다."""
        message = self._encode(device_id, status)
        asyncio.create_task(self.broadcast(message))

    async def broadcast(self, message: str) -> None:
        async with self._lock:
            connections = list(self._connections)
        stale: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_text(message)
            except Exception:
                stale.append(websocket)
        if stale:
            async with self._lock:
                for websocket in stale:
                    self._connections.discard(websocket)

    @staticmethod
    def _encode(device_id: str, status: DeviceStatus) -> str:
        return json.dumps(
            {"device_id": device_id, "status": dataclasses.asdict(status)}, ensure_ascii=False
        )


@router.websocket("/ws/status")
async def status_endpoint(websocket: WebSocket) -> None:
    broadcaster: StatusBroadcaster = websocket.app.state.broadcaster
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(websocket)
