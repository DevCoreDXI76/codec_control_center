# app/api/routes_logs.py
"""제어 이력 조회 API (PLAN.md Phase⑥)."""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Request

from app.core.history import ControlHistory

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def list_logs(request: Request, limit: int = 100, device_id: str | None = None) -> list[dict]:
    history: ControlHistory = request.app.state.history
    entries = history.list_recent(limit=limit, device_id=device_id)
    return [dataclasses.asdict(e) for e in entries]
