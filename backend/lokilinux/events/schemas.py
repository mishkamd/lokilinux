"""
LokiLinux — Observability pipeline event schemas.

EventIn is what producers submit (agent/metrics/security/... -> EVENT_RAW).
NormalizedEvent is what EventProcessorWorker builds after validation + dedup +
fingerprinting, and what actually lands in ClickHouse (see ch.py).
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID
import json

from pydantic import BaseModel, Field, field_validator, model_validator

from lokilinux.config import get_settings

ALLOWED_SOURCES = {
    "agent", "metrics", "security", "compliance", "patch",
    "network", "ansible", "job", "external", "otel",
}
SEVERITIES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class EventIn(BaseModel):
    model_config = {"extra": "forbid"}

    schema_version: int = 1
    source: str
    type: str = Field(pattern=r"^[a-z0-9_.]{3,128}$")
    severity: str = "INFO"
    host_id: str | None = None
    service: str | None = None
    timestamp: datetime | None = None  # server-stamped when absent
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _only_v1_supported(cls, v: int) -> int:
        if v != 1:
            raise ValueError("schema_version: only 1 is supported")
        return v

    @field_validator("source")
    @classmethod
    def _known_source(cls, v: str) -> str:
        if v not in ALLOWED_SOURCES:
            raise ValueError(f"source must be one of {sorted(ALLOWED_SOURCES)}")
        return v

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        return v

    @field_validator("timestamp")
    @classmethod
    def _reject_clock_skew(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        skew = abs((datetime.now(timezone.utc) - v).total_seconds())
        max_skew = get_settings().event_max_clock_skew_sec
        if skew > max_skew:
            raise ValueError(f"timestamp skew {skew:.0f}s exceeds max {max_skew}s")
        return v

    @model_validator(mode="after")
    def _reject_oversize_payload(self) -> "EventIn":
        size = len(json.dumps(self.payload, default=str).encode())
        max_bytes = get_settings().event_max_payload_bytes
        if size > max_bytes:
            raise ValueError(f"payload {size}B exceeds max {max_bytes}B")
        return self


class NormalizedEvent(EventIn):
    event_id: UUID
    tenant_id: str
    timestamp: datetime  # always set post-normalization
    fingerprint: str
