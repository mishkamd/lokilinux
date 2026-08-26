"""
LokiLinux — Incident / IncidentTimeline Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage
from lokilinux.signals.schemas import SignalResponse


class IncidentTimelineEntry(BaseModel):
    id: UUID
    ts: datetime
    kind: str
    message: str
    payload: dict

    model_config = {"from_attributes": True}


class IncidentResponse(BaseModel):
    id: UUID
    tenant_id: str
    title: str
    type: str
    severity: str
    status: str
    root_cause_signal_id: UUID | None = None
    confidence: float | None = None
    group_key: str | None = None
    started_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    acknowledged_at: datetime | None = None

    model_config = {"from_attributes": True}


IncidentListResponse = CursorPage[IncidentResponse]


class IncidentDetailResponse(IncidentResponse):
    signals: list[SignalResponse]
    timeline: list[IncidentTimelineEntry]
