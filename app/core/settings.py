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
}


@dataclass
class AppSettings:
    poll_interval: float = 15.0
    max_concurrency: int = 8
    command_timeout: float = 7.0
    open_browser_on_start: bool = True

    def __post_init__(self) -> None:
        if not (1.0 <= self.poll_interval <= 300.0):
            raise ValueError("poll_interval must be between 1 and 300 seconds")
        if not (1 <= self.max_concurrency <= 64):
            raise ValueError("max_concurrency must be between 1 and 64")
        if not (1.0 <= self.command_timeout <= 60.0):
            raise ValueError("command_timeout must be between 1 and 60 seconds")


class SettingsStore:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppSettings:
        if not self.store_path.exists():
            return AppSettings()
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        return AppSettings(**{**_DEFAULTS, **data})

    def save(self, settings: AppSettings) -> None:
        self.store_path.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
        )
