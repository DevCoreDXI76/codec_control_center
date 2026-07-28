import pytest
import pytest_asyncio

from app.core.driver_base import CalendarEntry
from app.drivers.cisco.cisco_driver import CiscoDriver
from app.simulator.cisco_sim_server import CiscoSimServer


@pytest_asyncio.fixture
async def sim_and_driver():
    sim = CiscoSimServer(host="127.0.0.1", port=0)
    sim.start()

    driver = CiscoDriver(host="127.0.0.1", port=sim.port, username="admin", password="x", timeout=5.0)
    await driver.connect()
    try:
        yield sim, driver
    finally:
        await driver.disconnect()
        sim.stop()


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
    assert await driver.dial("1234@example.com") is True
    assert sim.state.in_call is True

    status = await driver.get_status()
    assert status.in_call is True
    assert status.call_peer == "1234@example.com"


async def test_hangup_clears_call(sim_and_driver):
    sim, driver = sim_and_driver
    await driver.dial("1234@example.com")
    assert await driver.hangup() is True
    assert sim.state.in_call is False

    status = await driver.get_status()
    assert status.in_call is False


async def test_reboot_returns_true_without_hanging(sim_and_driver):
    _sim, driver = sim_and_driver
    assert await driver.reboot() is True


async def test_calendar_methods_raise_not_implemented(sim_and_driver):
    _sim, driver = sim_and_driver
    with pytest.raises(NotImplementedError):
        await driver.get_calendar_status()
    with pytest.raises(NotImplementedError):
        await driver.get_obtp_entries()


async def test_join_meeting_dials_join_uri(sim_and_driver):
    sim, driver = sim_and_driver
    entry = CalendarEntry(subject="Weekly", start_time="x", end_time="y", join_uri="sip:weekly@example.com")
    assert await driver.join_meeting(entry) is True
    assert sim.state.in_call is True
    assert sim.state.call_peer == "sip:weekly@example.com"


async def test_join_meeting_without_uri_raises(sim_and_driver):
    _sim, driver = sim_and_driver
    entry = CalendarEntry(subject="No URI", start_time="x", end_time="y", join_uri=None)
    with pytest.raises(Exception):
        await driver.join_meeting(entry)


async def test_full_lifecycle_no_exceptions(sim_and_driver):
    """Phase① DoD: connect/get_status/mute/dial/hangup/reboot 전부 예외 없이 동작."""
    _sim, driver = sim_and_driver
    await driver.get_status()
    await driver.mute(True)
    await driver.mute(False)
    await driver.dial("1234")
    await driver.hangup()
    await driver.reboot()
