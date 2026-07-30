# app/models/device.py
"""SPEC.md 6.1 데이터 모델 — 장비 레지스트리 항목."""
from __future__ import annotations

from dataclasses import dataclass

VALID_VENDORS = {"poly", "cisco"}
VALID_CONNECTION_TYPES = {"ssh", "telnet"}

_TENANT_ADDRESS_FORBIDDEN_CHARS = ('"', "'", "\r", "\n")


@dataclass
class Device:
    id: str
    name: str
    vendor: str  # "poly" | "cisco"
    connection_type: str  # "ssh" | "telnet"
    host: str
    port: int
    group: str
    credential_ref: str
    is_simulated: bool = False
    model: str | None = None
    teams_tenant_address: str | None = None

    def __post_init__(self) -> None:
        if self.vendor not in VALID_VENDORS:
            raise ValueError(f"invalid vendor: {self.vendor!r} (expected one of {VALID_VENDORS})")
        if self.connection_type not in VALID_CONNECTION_TYPES:
            raise ValueError(
                f"invalid connection_type: {self.connection_type!r} (expected one of {VALID_CONNECTION_TYPES})"
            )
        if self.teams_tenant_address and any(c in self.teams_tenant_address for c in _TENANT_ADDRESS_FORBIDDEN_CHARS):
            raise ValueError(
                "teams_tenant_address must not contain quotes or newline characters "
                f"(got {self.teams_tenant_address!r})"
            )
