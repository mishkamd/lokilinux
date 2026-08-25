"""
LokiLinux — Runbook Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RunbookCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    incident_type: str
    workflow_id: UUID | None = None
    trigger_mode: str = "MANUAL"  # MANUAL|AUTO
    min_severity: str = "HIGH"
    enabled: bool = True


class RunbookResponse(BaseModel):
    id: UUID
    tenant_id: str
    name: str
    incident_type: str
    workflow_id: UUID | None = None
    trigger_mode: str
    min_severity: str
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RunbookExecuteRequest(BaseModel):
    model_config = {"extra": "forbid"}

    incident_id: UUID | None = None
