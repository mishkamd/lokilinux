"""
LokiLinux — Remediation Engine Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class RemediationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class TriggerType(str, Enum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    AUTOMATIC = "AUTOMATIC"
    AI_SUGGESTED = "AI_SUGGESTED"


class RemediationActionCreate(BaseModel):
    agent_id: UUID
    provider: str  # ansible/shell/python/terraform
    rendered_body: str
    rule_id: UUID | None = None
    drift_event_id: UUID | None = None
    rollback_body: str | None = None


class RemediationActionResponse(BaseModel):
    id: UUID
    remediation_plan_id: UUID
    rule_id: UUID | None = None
    drift_event_id: UUID | None = None
    agent_id: UUID
    provider: str
    rendered_body: str
    rollback_body: str | None = None
    sequence: int

    model_config = {"from_attributes": True}


class RemediationPlanCreate(BaseModel):
    name: str
    trigger_type: TriggerType = TriggerType.MANUAL
    is_emergency: bool = False
    actions: list[RemediationActionCreate]


class RemediationPlanResponse(BaseModel):
    id: UUID
    name: str
    status: RemediationPlanStatus
    trigger_type: TriggerType
    is_emergency: bool
    created_by: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


RemediationPlanListResponse = CursorPage[RemediationPlanResponse]
