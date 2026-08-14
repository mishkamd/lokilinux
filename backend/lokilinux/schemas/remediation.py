"""
LokiLinux — Remediation Engine Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from lokilinux.schemas.common import CursorPage
from lokilinux.schemas.job import JobStatus


class RemediationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class TriggerType(str, Enum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    AUTOMATIC = "AUTOMATIC"
    AI_SUGGESTED = "AI_SUGGESTED"


RemediationProvider = Literal["ansible", "shell", "python"]


class RemediationActionCreate(BaseModel):
    agent_id: UUID
    provider: RemediationProvider
    rendered_body: str = Field(min_length=1)
    rule_id: UUID | None = None
    drift_event_id: UUID | None = None
    rollback_body: str | None = None


class RemediationActionResponse(BaseModel):
    id: UUID
    remediation_plan_id: UUID
    rule_id: UUID | None = None
    drift_event_id: UUID | None = None
    agent_id: UUID
    hostname: str | None = None
    provider: str
    rendered_body: str
    rollback_body: str | None = None
    sequence: int

    model_config = {"from_attributes": True}


class RemediationPlanCreate(BaseModel):
    name: str
    trigger_type: TriggerType = TriggerType.MANUAL
    is_emergency: bool = False
    maintenance_window_id: UUID | None = None
    actions: list[RemediationActionCreate]


class RemediationPlanResponse(BaseModel):
    id: UUID
    name: str
    status: RemediationPlanStatus
    trigger_type: TriggerType
    is_emergency: bool
    maintenance_window_id: UUID | None = None
    created_by: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


RemediationPlanListResponse = CursorPage[RemediationPlanResponse]


# ── Maintenance Windows ──────────────────────────────────────────────────────

ScopeType = Literal["GLOBAL", "OS", "ROLE", "ENVIRONMENT", "DATACENTER", "CLUSTER", "APPLICATION"]


class MaintenanceWindowCreate(BaseModel):
    name: str
    scope_type: ScopeType = "GLOBAL"
    scope_selector: dict = Field(default_factory=dict)
    cron_expr: str | None = None
    duration_minutes: int = Field(ge=1, le=1440)
    timezone: str = "UTC"
    is_enabled: bool = True


class MaintenanceWindowResponse(BaseModel):
    id: UUID
    name: str
    scope_type: str
    scope_selector: dict
    cron_expr: str | None = None
    duration_minutes: int
    timezone: str
    is_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Execution / Rollback ─────────────────────────────────────────────────────


class RemediationExecutionResult(BaseModel):
    agent_id: UUID
    hostname: str | None = None
    status: str
    exit_code: int | None = None
    error_message: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    duration_seconds: int | None = None


class RemediationExecutionResponse(BaseModel):
    job_id: UUID | None = None
    operation: Literal["APPLY", "ROLLBACK", "DRY_RUN"] | None = None
    job_status: JobStatus | None = None
    results: list[RemediationExecutionResult] = Field(default_factory=list)
