# app/core/vault.py
"""
Windows DPAPI(CryptProtectData) 기반 자격증명 저장소.

SPEC.md 6.1/9절: 장비 ID/PW 등 민감정보는 평문으로 저장하지 않는다.
CredentialVault가 DPAPI(현재 사용자 컨텍스트)로 암호화한 blob만 파일에 저장하고,
장비 레지스트리에는 이 blob을 가리키는 credential_ref(uuid)만 남긴다.
복호화는 필요한 순간에만 메모리에서 수행하며, 결과를 로그로 남기지 않는다.
"""
from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

from app.core import dpapi

_ENTROPY = b"codec-control-center"


class CredentialVault:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write_store({})

    def store(self, plaintext: str) -> str:
        """평문을 DPAPI로 암호화해 저장하고, 조회에 쓸 credential_ref를 반환한다."""
        encrypted = dpapi.protect(plaintext.encode("utf-8"), _ENTROPY)
        credential_ref = str(uuid.uuid4())
        data = self._read_store()
        data[credential_ref] = base64.b64encode(encrypted).decode("ascii")
        self._write_store(data)
        return credential_ref

    def load(self, credential_ref: str) -> str:
        """credential_ref에 대응하는 평문을 복호화해 반환한다 (현재 Windows 사용자 계정에서만 가능)."""
        data = self._read_store()
        if credential_ref not in data:
            raise KeyError(f"unknown credential_ref: {credential_ref}")
        encrypted = base64.b64decode(data[credential_ref])
        return dpapi.unprotect(encrypted, _ENTROPY).decode("utf-8")

    def delete(self, credential_ref: str) -> None:
        data = self._read_store()
        if credential_ref in data:
            del data[credential_ref]
            self._write_store(data)

    def _read_store(self) -> dict[str, str]:
        if not self.store_path.exists():
            return {}
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _write_store(self, data: dict[str, str]) -> None:
        self.store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
