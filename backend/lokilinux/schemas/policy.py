"""
LokiLinux — Policy Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, model_validator

from lokilinux.schemas.common import CursorPage


class PolicyType(str, Enum):
    UPDATE = "UPDATE"
    SECURITY = "SECURITY"
    COMPLIANCE = "COMPLIANCE"
    MAINTENANCE = "MAINTENANCE"
    PLUGIN = "PLUGIN"


class TriggerType(str, Enum):
    MANUAL = "MANUAL"
    SCHEDULE = "SCHEDULE"


class PolicyAction(BaseModel):
    """One action a policy run executes. Phase 1 only ever runs actions[0] —
    kept as a list on the model so multi-step orchestration (Phase 2+) is an
    additive change, not another migration."""

    type: str  # PACKAGE_UPDATE / CUSTOM_COMMAND today
    params: dict = {}


class PolicyExecution(BaseModel):
    requires_approval: bool = False
    timeout_seconds: int | None = None


class PolicyBase(BaseModel):
    name: str
    description: str | None = None
    policy_type: PolicyType | None = None
    rules: dict = {}
    target_servers: dict | None = None
    is_enabled: bool = True
    priority: int = 100
    trigger_type: TriggerType = TriggerType.MANUAL
    cron_expr: str | None = None
    actions: list[PolicyAction] = []
    execution: PolicyExecution = PolicyExecution()
    severity: str | None = None
    tags: list[str] = []

    @model_validator(mode="after")
    def _cron_required_for_schedule(self) -> "PolicyBase":
        if self.trigger_type == TriggerType.SCHEDULE and not self.cron_expr:
            raise ValueError("cron_expr is required when trigger_type is SCHEDULE")
        return self


class PolicyCreate(PolicyBase):
    pass


class PolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    rules: dict | None = None
    target_servers: dict | None = None
    is_enabled: bool | None = None
    priority: int | None = None
    trigger_type: TriggerType | None = None
    cron_expr: str | None = None
    actions: list[PolicyAction] | None = None
    execution: PolicyExecution | None = None
    severity: str | None = None
    tags: list[str] | None = None


class PolicyResponse(PolicyBase):
    id: UUID
    version: int = 1
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None

    model_config = {"from_attributes": True}


PolicyListResponse = CursorPage[PolicyResponse]


class PolicyAuditResponse(BaseModel):
    id: int
    policy_id: UUID
    changed_by: UUID | None = None
    change_type: str
    old_value: dict | None = None
    new_value: dict | None = None
    changed_at: datetime

    model_config = {"from_attributes": True}


class PolicyRunResponse(BaseModel):
    job_ids: list[UUID]
    matched_agents: int
