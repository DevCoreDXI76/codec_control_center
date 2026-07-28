import asyncio
import json

from app.api.ws_status import StatusBroadcaster
from app.core.driver_base import DeviceStatus
from app.main import app


class FakeWebSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.received: list[str] = []

    async def send_text(self, message: str) -> None:
        if self.fail:
            raise RuntimeError("connection closed")
        self.received.append(message)


def _sample_status() -> DeviceStatus:
    return DeviceStatus(online=True, in_call=False, muted=True, call_peer=None, last_polled_at="now")


async def test_broadcast_sends_to_all_connections():
    broadcaster = StatusBroadcaster()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    broadcaster._connections.update({ws1, ws2})

    await broadcaster.broadcast("hello")

    assert ws1.received == ["hello"]
    assert ws2.received == ["hello"]


async def test_broadcast_prunes_failing_connections():
    broadcaster = StatusBroadcaster()
    ok, broken = FakeWebSocket(), FakeWebSocket(fail=True)
    broadcaster._connections.update({ok, broken})

    await broadcaster.broadcast("hello")

    assert ok in broadcaster._connections
    assert broken not in broadcaster._connections


async def test_notify_encodes_device_status_as_json():
    broadcaster = StatusBroadcaster()
    ws = FakeWebSocket()
    broadcaster._connections.add(ws)

    broadcaster.notify("dev-1", _sample_status())
    await asyncio.sleep(0)  # notify()가 create_task로 예약한 브로드캐스트가 실행되도록 양보

    assert len(ws.received) == 1
    payload = json.loads(ws.received[0])
    assert payload["device_id"] == "dev-1"
    assert payload["status"]["online"] is True
    assert payload["status"]["muted"] is True


def test_websocket_endpoint_connect_and_disconnect():
    app.state.broadcaster = StatusBroadcaster()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    with client.websocket_connect("/ws/status") as ws:
        pass  # 연결/종료가 예외 없이 이뤄지는지만 확인
