"""
LokiLinux — Signal / CorrelationRule Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class SignalResponse(BaseModel):
    id: UUID
    tenant_id: str
    type: str
    severity: str
    status: str
    host_id: UUID | None = None
    service: str | None = None
    fingerprint: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}


SignalListResponse = CursorPage[SignalResponse]


class CorrelationRuleResponse(BaseModel):
    id: UUID
    tenant_id: str
    name: str
    enabled: bool
    window_seconds: int
    group_by: list
    conditions: list
    threshold_score: int
    incident_type: str
    incident_severity: str
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


CorrelationRuleListResponse = CursorPage[CorrelationRuleResponse]
