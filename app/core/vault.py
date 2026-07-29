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

SCHEMA_VERSION = 1
"""credentials.enc.json 저장 형식 버전. 구조 변경 시 올리고,
_migrate()에 "if version < N: ..." 형태로 단계별 변환을 추가한다."""


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
        payload = _migrate(json.loads(self.store_path.read_text(encoding="utf-8")))
        return payload["credentials"]

    def _write_store(self, data: dict[str, str]) -> None:
        payload = {"schema_version": SCHEMA_VERSION, "credentials": data}
        self.store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _migrate(payload: dict) -> dict:
    """구버전 credentials.enc.json을 현재 스키마로 변환한다.

    schema_version 필드가 없는 파일은 1.0.0 이전의 평면 구조({credential_ref: blob, ...})다 —
    credentials 키로 감싸서 승격한다.
    """
    if "schema_version" not in payload:
        return {"schema_version": SCHEMA_VERSION, "credentials": payload}
    version = payload["schema_version"]
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"credentials.enc.json schema_version={version}이 현재 앱이 지원하는 "
            f"최대 버전({SCHEMA_VERSION})보다 높습니다 — 더 최신 버전의 앱으로 실행해주세요."
        )
    return payload
