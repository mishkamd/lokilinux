"""
LokiLinux — Baseline Manager Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class ScopeType(str, Enum):
    GLOBAL = "GLOBAL"
    OS = "OS"
    ROLE = "ROLE"
    ENVIRONMENT = "ENVIRONMENT"
    DATACENTER = "DATACENTER"
    CLUSTER = "CLUSTER"
    APPLICATION = "APPLICATION"


class BaselineVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class BaselineCreate(BaseModel):
    name: str
    description: str | None = None
    scope_type: ScopeType
    scope_selector: dict = {}
    parent_baseline_id: UUID | None = None
    expected_state: dict = {}  # seeds baseline_versions version 1 (DRAFT)


class BaselineResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    scope_type: ScopeType
    scope_selector: dict
    parent_baseline_id: UUID | None = None
    is_enabled: bool
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


BaselineListResponse = CursorPage[BaselineResponse]


class BaselineVersionCreate(BaseModel):
    expected_state: dict
    change_summary: str | None = None


class BaselineVersionResponse(BaseModel):
    id: UUID
    baseline_id: UUID
    version: int
    status: BaselineVersionStatus
    expected_state: dict
    content_hash: str
    signed_by: UUID | None = None
    change_summary: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    published_at: datetime | None = None
    deprecated_at: datetime | None = None

    model_config = {"from_attributes": True}


class BaselineApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BaselineApprovalCreate(BaseModel):
    decision: BaselineApprovalDecision
    comment: str | None = None


class BaselineApprovalResponse(BaseModel):
    id: int
    baseline_version_id: UUID
    approver_id: UUID
    decision: BaselineApprovalDecision
    comment: str | None = None
    decided_at: datetime

    model_config = {"from_attributes": True}


class EffectiveBaselineResponse(BaseModel):
    agent_id: UUID
    baseline_version_ids: list[UUID]
    merged_state: dict
    merged_hash: str
    computed_at: datetime

    model_config = {"from_attributes": True}
