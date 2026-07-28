# app/core/dpapi.py
"""Windows DPAPI(CryptProtectData/CryptUnprotectData) 저수준 래퍼.

CredentialVault, DeviceRegistry가 공통으로 사용하는 암호화/복호화 헬퍼.
현재 Windows 사용자 컨텍스트에서만 복호화 가능하다.
"""
from __future__ import annotations

import win32crypt


def protect(data: bytes, entropy: bytes) -> bytes:
    return win32crypt.CryptProtectData(data, None, entropy, None, None, 0)


def unprotect(data: bytes, entropy: bytes) -> bytes:
    _description, decrypted = win32crypt.CryptUnprotectData(data, entropy, None, None, 0)
    return decrypted
