import pytest

from app.core.vault import CredentialVault


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
