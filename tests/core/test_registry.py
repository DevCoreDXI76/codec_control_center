import json

import pytest

from app.core import dpapi
from app.core.registry import DeviceRegistry, SCHEMA_VERSION, _ENTROPY, _migrate


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


def test_write_includes_schema_version(registry, tmp_path):
    _add_sample(registry)
    raw = dpapi.unprotect((tmp_path / "devices.enc.json").read_bytes(), _ENTROPY)
    assert json.loads(raw)["schema_version"] == SCHEMA_VERSION


def test_migrate_missing_schema_version_defaults_to_1():
    payload = {"devices": [{"id": "x"}]}
    assert _migrate(payload) == payload


def test_migrate_future_version_raises():
    with pytest.raises(ValueError):
        _migrate({"schema_version": SCHEMA_VERSION + 1, "devices": []})


def test_reads_legacy_file_without_schema_version(tmp_path):
    path = tmp_path / "devices.enc.json"
    legacy = json.dumps({"devices": []}, ensure_ascii=False).encode("utf-8")
    path.write_bytes(dpapi.protect(legacy, _ENTROPY))
    assert DeviceRegistry(path).list_devices() == []


def test_model_defaults_to_none(registry):
    device = _add_sample(registry)
    assert device.model is None


def test_teams_tenant_address_can_be_set(registry):
    device = _add_sample(registry, teams_tenant_address="vc.poscodx.com")
    assert device.teams_tenant_address == "vc.poscodx.com"
    assert registry.get_device(device.id).teams_tenant_address == "vc.poscodx.com"


def test_teams_tenant_address_empty_string_is_accepted(registry):
    device = _add_sample(registry, teams_tenant_address="")
    assert device.teams_tenant_address == ""


def test_teams_tenant_address_none_is_accepted(registry):
    device = _add_sample(registry, teams_tenant_address=None)
    assert device.teams_tenant_address is None


@pytest.mark.parametrize("bad_value", ['vc"poscodx.com', "vc'poscodx.com", "vc.poscodx.com\n@evil", "vc.poscodx.com\rX"])
def test_teams_tenant_address_rejects_dangerous_characters(registry, bad_value):
    with pytest.raises(ValueError):
        _add_sample(registry, teams_tenant_address=bad_value)


def test_update_device_sets_model(registry):
    device = _add_sample(registry)
    updated = registry.update_device(device.id, model="RealPresence Group 700")
    assert updated.model == "RealPresence Group 700"
    assert registry.get_device(device.id).model == "RealPresence Group 700"


def test_reads_legacy_device_without_model_field(tmp_path):
    path = tmp_path / "devices.enc.json"
    legacy_device = {
        "id": "legacy-1", "name": "구버전 장비", "vendor": "poly", "connection_type": "telnet",
        "host": "127.0.0.1", "port": 2323, "group": "3F", "credential_ref": "ref-1",
        "is_simulated": True,
    }
    payload = json.dumps({"schema_version": SCHEMA_VERSION, "devices": [legacy_device]}, ensure_ascii=False).encode("utf-8")
    path.write_bytes(dpapi.protect(payload, _ENTROPY))

    devices = DeviceRegistry(path).list_devices()
    assert len(devices) == 1
    assert devices[0].model is None
    assert devices[0].teams_tenant_address is None
