"""시스템 로그(data/app.log) 조회 유틸 — /logs/system 뷰어에서 사용."""
from __future__ import annotations

from pathlib import Path


def tail_app_log(path: Path, n: int = 300) -> list[str]:
    """app.log의 마지막 n줄을 최신순(역순)으로 반환한다. 파일이 없으면 빈 리스트."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return list(reversed(lines[-n:]))
