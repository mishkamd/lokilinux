"""
LokiLinux — Alert / AlertRule Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class AlertResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    severity: str | None = None
    status: str
    alert_type: str | None = None
    agent_id: UUID | None = None
    hostname: str | None = None
    triggered_at: datetime
    created_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}


AlertListResponse = CursorPage[AlertResponse]


class AlertRuleResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    conditions: dict
    alert_severity: str | None = None
    is_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


AlertRuleListResponse = CursorPage[AlertRuleResponse]
