# app/core/settings.py
"""앱 설정 저장/조회 (UX_SPEC.md 4.6절).

폴링 주기/동시 접속 제한/명령 타임아웃 등은 민감정보가 아니므로
DPAPI 암호화 없이 평문 JSON으로 저장한다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

_DEFAULTS = {
    "poll_interval": 15.0,
    "max_concurrency": 8,
    "command_timeout": 7.0,
    "open_browser_on_start": True,
    "teams_tenant_address": "",
}

SCHEMA_VERSION = 1
"""settings.json 저장 형식 버전. 필드 추가/구조 변경 시 올리고,
_migrate()에 "if version < N: ..." 형태로 단계별 변환을 추가한다."""

_TENANT_ADDRESS_FORBIDDEN_CHARS = ('"', "'", "\r", "\n")


@dataclass
class AppSettings:
    poll_interval: float = 15.0
    max_concurrency: int = 8
    command_timeout: float = 7.0
    open_browser_on_start: bool = True
    teams_tenant_address: str = ""

    def __post_init__(self) -> None:
        if not (1.0 <= self.poll_interval <= 300.0):
            raise ValueError("poll_interval must be between 1 and 300 seconds")
        if not (1 <= self.max_concurrency <= 64):
            raise ValueError("max_concurrency must be between 1 and 64")
        if not (1.0 <= self.command_timeout <= 60.0):
            raise ValueError("command_timeout must be between 1 and 60 seconds")
        if self.teams_tenant_address and any(c in self.teams_tenant_address for c in _TENANT_ADDRESS_FORBIDDEN_CHARS):
            raise ValueError(
                "teams_tenant_address must not contain quotes or newline characters "
                f"(got {self.teams_tenant_address!r})"
            )


class SettingsStore:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppSettings:
        if not self.store_path.exists():
            return AppSettings()
        data = _migrate(json.loads(self.store_path.read_text(encoding="utf-8")))
        data.pop("schema_version", None)
        return AppSettings(**{**_DEFAULTS, **data})

    def save(self, settings: AppSettings) -> None:
        payload = {"schema_version": SCHEMA_VERSION, **asdict(settings)}
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _migrate(data: dict) -> dict:
    """구버전 settings.json을 현재 스키마로 변환한다.

    schema_version 필드가 없는 파일(1.0.0 이전, 이 필드가 생기기 전)은 1로 간주한다.
    """
    version = data.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"settings.json schema_version={version}이 현재 앱이 지원하는 "
            f"최대 버전({SCHEMA_VERSION})보다 높습니다 — 더 최신 버전의 앱으로 실행해주세요."
        )
    return data
