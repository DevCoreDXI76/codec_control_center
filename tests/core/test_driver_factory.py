import json

import pytest

from app.core.driver_factory import build_driver_factory
from app.core.registry import DeviceRegistry
from app.core.vault import CredentialVault
from app.drivers.cisco.cisco_driver import CiscoDriver
from app.drivers.poly.poly_driver import PolyDriver


@pytest.fixture
def registry(tmp_path):
    return DeviceRegistry(tmp_path / "devices.enc.json")


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "credentials.enc.json")


def test_builds_poly_driver(registry, vault):
    credential_ref = vault.store(json.dumps({"username": "admin", "password": "pw"}))
    device = registry.add_device(
        name="poly room", vendor="poly", connection_type="telnet",
        host="127.0.0.1", port=2323, group="3F", credential_ref=credential_ref, is_simulated=True,
    )
    factory = build_driver_factory(registry, vault)
    driver = factory(device.id)
    assert isinstance(driver, PolyDriver)
    assert driver.host == "127.0.0.1"
    assert driver.port == 2323


def test_builds_cisco_driver_with_credentials(registry, vault):
    credential_ref = vault.store(json.dumps({"username": "admin", "password": "s3cret"}))
    device = registry.add_device(
        name="cisco room", vendor="cisco", connection_type="ssh",
        host="127.0.0.1", port=2222, group="5F", credential_ref=credential_ref, is_simulated=True,
    )
    factory = build_driver_factory(registry, vault)
    driver = factory(device.id)
    assert isinstance(driver, CiscoDriver)
    assert driver.host == "127.0.0.1"
    assert driver.port == 2222
    assert driver.username == "admin"
    assert driver.password == "s3cret"


def test_unknown_device_raises_keyerror(registry, vault):
    factory = build_driver_factory(registry, vault)
    with pytest.raises(KeyError):
        factory("no-such-id")
