"""
LokiLinux — Drift Detection Pydantic schemas.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class DriftEventResponse(BaseModel):
    id: UUID
    time: datetime
    agent_id: UUID
    hostname: str | None = None
    domain: str
    compared_against: str
    severity: str
    change_type: str
    summary: str
    acknowledged_by: UUID | None = None
    acknowledged_at: datetime | None = None
    status: str = "OPEN"
    occurrences: int = 1
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    correlation_key: str | None = None
    resolved_at: datetime | None = None
    suppressed_by: UUID | None = None

    model_config = {"from_attributes": True}


DriftEventListResponse = CursorPage[DriftEventResponse]


class DriftDetailResponse(BaseModel):
    drift_event_id: UUID
    field_path: str
    old_value: Any | None = None
    new_value: Any | None = None

    model_config = {"from_attributes": True}
