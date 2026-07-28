import pytest

from app.core.registry import DeviceRegistry


@pytest.fixture
def registry(tmp_path):
    return DeviceRegistry(tmp_path / "devices.enc.json")


def _add_sample(registry, **overrides):
    defaults = dict(
        name="3층 대회의실",
        vendor="poly",
        connection_type="telnet",
        host="127.0.0.1",
        port=2323,
        group="3F",
        credential_ref="cred-ref-1",
        is_simulated=True,
    )
    defaults.update(overrides)
    return registry.add_device(**defaults)


def test_add_and_list_device(registry):
    device = _add_sample(registry)
    devices = registry.list_devices()
    assert len(devices) == 1
    assert devices[0].id == device.id
    assert devices[0].name == "3층 대회의실"


def test_get_device_by_id(registry):
    device = _add_sample(registry)
    fetched = registry.get_device(device.id)
    assert fetched is not None
    assert fetched.host == "127.0.0.1"


def test_get_device_unknown_id_returns_none(registry):
    assert registry.get_device("no-such-id") is None


def test_update_device(registry):
    device = _add_sample(registry)
    updated = registry.update_device(device.id, name="5층 소회의실", port=2324)
    assert updated.name == "5층 소회의실"
    assert updated.port == 2324
    assert registry.get_device(device.id).name == "5층 소회의실"


def test_update_unknown_device_raises_keyerror(registry):
    with pytest.raises(KeyError):
        registry.update_device("no-such-id", name="x")


def test_delete_device(registry):
    device = _add_sample(registry)
    registry.delete_device(device.id)
    assert registry.get_device(device.id) is None
    assert registry.list_devices() == []


def test_invalid_vendor_raises_valueerror(registry):
    with pytest.raises(ValueError):
        _add_sample(registry, vendor="yealink")


def test_invalid_connection_type_raises_valueerror(registry):
    with pytest.raises(ValueError):
        _add_sample(registry, connection_type="http")


def test_registry_file_is_encrypted_not_plain_json(registry, tmp_path):
    _add_sample(registry, name="비밀회의실")
    raw = (tmp_path / "devices.enc.json").read_bytes()
    assert b"devices" not in raw
    assert "비밀회의실".encode("utf-8") not in raw


def test_persists_across_registry_instances(tmp_path):
    path = tmp_path / "devices.enc.json"
    device = DeviceRegistry(path).add_device(
        name="영속성 테스트",
        vendor="cisco",
        connection_type="ssh",
        host="10.0.0.5",
        port=22,
        group="본사",
        credential_ref="cred-ref-2",
    )
    reopened = DeviceRegistry(path)
    fetched = reopened.get_device(device.id)
    assert fetched is not None
    assert fetched.name == "영속성 테스트"
