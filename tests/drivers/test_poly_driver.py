import asyncio

import pytest
import pytest_asyncio

from app.core.driver_base import CalendarEntry
from app.drivers.poly.poly_driver import PolyDriver, _parse_uptime
from app.simulator.poly_sim_server import PolySimServer, PolySSHSimServer


@pytest_asyncio.fixture
async def sim_and_driver():
    sim = PolySimServer(host="127.0.0.1", port=0)
    await sim.start()
    port = sim._server.sockets[0].getsockname()[1]

    driver = PolyDriver(host="127.0.0.1", port=port, timeout=3.0)
    await driver.connect()
    try:
        yield sim, driver
    finally:
        await driver.disconnect()
        await sim.stop()


@pytest_asyncio.fixture
async def ssh_sim_and_driver():
    sim = PolySSHSimServer(host="127.0.0.1", port=0)
    await asyncio.to_thread(sim.start)

    driver = PolyDriver(
        host="127.0.0.1", port=sim.port, timeout=3.0, transport="ssh", username="admin", password="pw"
    )
    await driver.connect()
    try:
        yield sim, driver
    finally:
        await driver.disconnect()
        await asyncio.to_thread(sim.stop)


async def test_get_status_idle(sim_and_driver):
    _sim, driver = sim_and_driver
    status = await driver.get_status()
    assert status.online is True
    assert status.in_call is False
    assert status.muted is False
    assert status.error is None


async def test_mute_unmute_reflected_in_status(sim_and_driver):
    sim, driver = sim_and_driver
    assert await driver.mute(True) is True
    assert sim.state.muted is True
    status = await driver.get_status()
    assert status.muted is True

    assert await driver.mute(False) is True
    assert sim.state.muted is False


async def test_dial_then_status_shows_in_call(sim_and_driver):
    sim, driver = sim_and_driver
    assert await driver.dial("5551212") is True
    assert sim.state.in_call is True

    status = await driver.get_status()
    assert status.in_call is True
    assert status.call_peer == "5551212"


async def test_hangup_clears_call(sim_and_driver):
    sim, driver = sim_and_driver
    await driver.dial("5551212")
    assert await driver.hangup() is True
    assert sim.state.in_call is False

    status = await driver.get_status()
    assert status.in_call is False


async def test_reboot_returns_true_without_hanging(sim_and_driver):
    _sim, driver = sim_and_driver
    assert await driver.reboot() is True


async def test_get_calendar_status_registered(sim_and_driver):
    _sim, driver = sim_and_driver
    assert await driver.get_calendar_status() == "registered"


async def test_get_calendar_status_not_registered(sim_and_driver):
    sim, driver = sim_and_driver
    sim.state.calendar_established = False
    assert await driver.get_calendar_status() == "not_registered"


async def test_get_obtp_entries_returns_seeded_meeting(sim_and_driver):
    _sim, driver = sim_and_driver
    entries = await driver.get_obtp_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, CalendarEntry)
    assert entry.subject == "주간 전체회의"
    assert entry.join_uri == "sip:weekly@example.com"


async def test_join_meeting_dials_join_uri(sim_and_driver):
    sim, driver = sim_and_driver
    entries = await driver.get_obtp_entries()
    assert await driver.join_meeting(entries[0]) is True
    assert sim.state.in_call is True
    assert sim.state.call_peer == "sip:weekly@example.com"


async def test_full_lifecycle_no_exceptions(sim_and_driver):
    """Phase① DoD: connect/get_status/mute/dial/hangup/reboot 전부 예외 없이 동작."""
    _sim, driver = sim_and_driver
    await driver.get_status()
    await driver.mute(True)
    await driver.mute(False)
    await driver.dial("1234")
    await driver.hangup()
    await driver.reboot()


async def test_get_status_includes_model_and_uptime(sim_and_driver):
    _sim, driver = sim_and_driver
    status = await driver.get_status()
    assert status.model == "RealPresence Group 500 (SIM)"
    assert status.uptime_seconds is not None


async def test_get_status_uptime_failure_still_reports_online():
    """uptime get만 실패(무응답)해도 mute/callinfo 조회는 정상 진행되어
    online=True를 유지해야 한다 — uptime 실패가 전체 offline 판정으로
    번지지 않도록 get_status()가 uptime 조회를 개별 보호하는지 검증.
    (짧은 timeout으로 타임아웃 대기를 최소화)"""
    sim = PolySimServer(host="127.0.0.1", port=0)
    await sim.start()
    port = sim._server.sockets[0].getsockname()[1]

    driver = PolyDriver(host="127.0.0.1", port=port, timeout=0.5)
    await driver.connect()
    try:
        sim.state.uptime_fails = True
        status = await driver.get_status()
    finally:
        await driver.disconnect()
        await sim.stop()

    assert status.online is True
    assert status.error is None
    assert status.uptime_seconds is None
    assert status.model == "RealPresence Group 500 (SIM)"


def test_invalid_transport_raises_valueerror():
    with pytest.raises(ValueError):
        PolyDriver(host="127.0.0.1", transport="http")


# --- SSH 트랜스포트 (Phase③ 실장비 검증: connection_type="ssh" 장비 대응) ---
# 동일 명령 세트를 SSH로 접속해도 동작함을 확인 — 위 Telnet 테스트와 대칭.


async def test_ssh_get_status_idle(ssh_sim_and_driver):
    _sim, driver = ssh_sim_and_driver
    status = await driver.get_status()
    assert status.online is True
    assert status.error is None


async def test_ssh_mute_unmute_reflected_in_status(ssh_sim_and_driver):
    sim, driver = ssh_sim_and_driver
    assert await driver.mute(True) is True
    assert sim.state.muted is True
    status = await driver.get_status()
    assert status.muted is True


async def test_ssh_full_lifecycle_no_exceptions(ssh_sim_and_driver):
    _sim, driver = ssh_sim_and_driver
    await driver.get_status()
    await driver.mute(True)
    await driver.dial("1234")
    await driver.hangup()
    await driver.reboot()


def test_parse_uptime_hours_and_minutes():
    assert _parse_uptime("1 Hour, 10 Minutes") == 4200


def test_parse_uptime_minutes_only():
    assert _parse_uptime("45 Minutes") == 2700


def test_parse_uptime_days_hours_minutes():
    assert _parse_uptime("3 Days, 2 Hours, 5 Minutes") == 3 * 86400 + 2 * 3600 + 5 * 60


def test_parse_uptime_unparseable_returns_none():
    assert _parse_uptime("garbage response") is None
