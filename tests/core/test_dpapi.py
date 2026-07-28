from app.core import dpapi


def test_protect_unprotect_roundtrip():
    plaintext = "roundtrip-value".encode("utf-8")
    encrypted = dpapi.protect(plaintext, b"entropy-a")
    assert encrypted != plaintext
    assert dpapi.unprotect(encrypted, b"entropy-a") == plaintext


def test_wrong_entropy_fails_to_decrypt():
    encrypted = dpapi.protect(b"secret", b"entropy-a")
    try:
        dpapi.unprotect(encrypted, b"entropy-b")
        assert False, "expected decryption to fail with mismatched entropy"
    except Exception:
        pass
