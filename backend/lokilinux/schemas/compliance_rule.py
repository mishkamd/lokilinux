"""
LokiLinux — Compliance Policy Engine Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class CheckSource(str, Enum):
    CEL = "CEL"
    OVAL_UNMAPPED = "OVAL_UNMAPPED"
    OSCAP_FALLBACK = "OSCAP_FALLBACK"


class ComplianceRuleResponse(BaseModel):
    id: UUID
    rule_key: str
    title: str
    description: str | None = None
    rationale: str | None = None
    severity: str
    domain: str
    check_source: CheckSource
    check_expr: str | None = None
    expected_value: dict | None = None
    platform_filter: list[str]
    standard_refs: dict
    remediation_template_id: UUID | None = None
    source: str
    source_version: str | None = None
    is_enabled: bool
    imported_at: datetime

    model_config = {"from_attributes": True}


ComplianceRuleListResponse = CursorPage[ComplianceRuleResponse]


class RuleCoverageResponse(BaseModel):
    rule_id: UUID
    rule_key: str
    check_source: CheckSource
    # fleet-wide breakdown of how this rule has actually been evaluated so far,
    # not just its static check_source — a CEL rule can still show 0 evaluations
    # if no agent has reported the relevant domain yet.
    evaluated_agent_count: int


class RemediationTemplateResponse(BaseModel):
    id: UUID
    rule_key: str
    provider: str
    body: str
    source: str
    git_path: str | None = None
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PolicySetCreate(BaseModel):
    name: str
    slug: str
    framework: str
    version: str | None = None
    description: str | None = None


class PolicySetResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    framework: str
    version: str | None = None
    description: str | None = None
    source_profile: str | None = None
    is_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


PolicySetListResponse = CursorPage[PolicySetResponse]


class PolicySetCoverageResponse(BaseModel):
    policy_set_id: UUID
    mapped: int
    unmapped: int
    coverage_pct: float


class PolicySetRuleAdd(BaseModel):
    rule_id: UUID
    severity_override: str | None = None


class PolicySetImportRequest(BaseModel):
    source: str = "complianceascode"
    profile_id: str | None = None
    content_version: str
    datastream_url: str


class PolicySetImportResponse(BaseModel):
    job_id: UUID
    status: str


class PolicyAssignmentCreate(BaseModel):
    policy_set_id: UUID
    scope_type: str
    scope_selector: dict = {}


class PolicyAssignmentResponse(BaseModel):
    id: UUID
    policy_set_id: UUID
    scope_type: str
    scope_selector: dict
    is_enabled: bool
    created_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
