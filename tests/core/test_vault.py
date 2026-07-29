import json

import pytest

from app.core.vault import CredentialVault, SCHEMA_VERSION, _migrate


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "credentials.enc.json")


def test_store_and_load_roundtrip(vault):
    ref = vault.store("s3cr3t-password")
    assert vault.load(ref) == "s3cr3t-password"


def test_store_returns_unique_refs(vault):
    ref1 = vault.store("password-one")
    ref2 = vault.store("password-two")
    assert ref1 != ref2
    assert vault.load(ref1) == "password-one"
    assert vault.load(ref2) == "password-two"


def test_plaintext_not_stored_on_disk(vault, tmp_path):
    vault.store("very-secret-value")
    raw = (tmp_path / "credentials.enc.json").read_text(encoding="utf-8")
    assert "very-secret-value" not in raw


def test_load_unknown_ref_raises_keyerror(vault):
    with pytest.raises(KeyError):
        vault.load("no-such-ref")


def test_delete_removes_entry(vault):
    ref = vault.store("to-be-deleted")
    vault.delete(ref)
    with pytest.raises(KeyError):
        vault.load(ref)


def test_delete_unknown_ref_is_noop(vault):
    vault.delete("no-such-ref")  # 예외 없이 조용히 무시


def test_store_persists_across_vault_instances(tmp_path):
    path = tmp_path / "credentials.enc.json"
    ref = CredentialVault(path).store("persisted-secret")
    reopened = CredentialVault(path)
    assert reopened.load(ref) == "persisted-secret"


def test_write_includes_schema_version(vault, tmp_path):
    vault.store("x")
    raw = json.loads((tmp_path / "credentials.enc.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION
    assert "credentials" in raw


def test_migrate_wraps_legacy_flat_format():
    legacy = {"ref-1": "blob-1"}
    migrated = _migrate(legacy)
    assert migrated == {"schema_version": SCHEMA_VERSION, "credentials": {"ref-1": "blob-1"}}


def test_migrate_future_version_raises():
    with pytest.raises(ValueError):
        _migrate({"schema_version": SCHEMA_VERSION + 1, "credentials": {}})


def test_reads_legacy_flat_format_file(tmp_path):
    path = tmp_path / "credentials.enc.json"
    path.write_text(json.dumps({"ref-legacy": "blob-legacy"}), encoding="utf-8")
    vault = CredentialVault(path)
    data = vault._read_store()
    assert data == {"ref-legacy": "blob-legacy"}
