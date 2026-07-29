# app/core/history.py
"""제어 명령 이력 저장 (PLAN.md Phase⑥ — SQLite 영속 저장)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
"""history.sqlite3 테이블 구조 버전. SQLite 내장 PRAGMA user_version에 저장한다.
구조 변경 시 올리고, _init_schema()에 "if current < N: ALTER TABLE ..." 형태로
단계별 마이그레이션을 추가한다."""


@dataclass
class LogEntry:
    id: int
    device_id: str
    device_name: str
    action: str
    success: bool
    detail: str | None
    created_at: str


class ControlHistory:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS control_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current == 0:
                # 방금 새로 만든 DB — 현재 스키마 버전으로 표시.
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif current > SCHEMA_VERSION:
                raise ValueError(
                    f"history.sqlite3 schema_version={current}이 현재 앱이 지원하는 "
                    f"최대 버전({SCHEMA_VERSION})보다 높습니다 — 더 최신 버전의 앱으로 실행해주세요."
                )
            # 0 < current < SCHEMA_VERSION인 구버전 DB는 여기서 ALTER TABLE 등으로 승격시키고
            # 마지막에 PRAGMA user_version = SCHEMA_VERSION으로 갱신한다 (아직 해당 사항 없음).

    def log(
        self,
        *,
        device_id: str,
        device_name: str,
        action: str,
        success: bool,
        detail: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO control_log (device_id, device_name, action, success, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    device_id,
                    device_name,
                    action,
                    1 if success else 0,
                    detail,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_recent(self, limit: int = 100, device_id: str | None = None) -> list[LogEntry]:
        query = "SELECT * FROM control_log"
        params: list = []
        if device_id:
            query += " WHERE device_id = ?"
            params.append(device_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            LogEntry(
                id=row["id"],
                device_id=row["device_id"],
                device_name=row["device_name"],
                action=row["action"],
                success=bool(row["success"]),
                detail=row["detail"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
