import pytest_asyncio

from app.core.driver_base import CalendarEntry
from app.drivers.poly.poly_driver import PolyDriver
from app.simulator.poly_sim_server import PolySimServer


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
