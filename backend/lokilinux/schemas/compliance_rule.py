"""
LokiLinux — Compliance Policy Engine Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from typing import Any
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
    # JSONB — curated content stores scalars (e.g. "no", true), not just objects
    expected_value: Any | None = None
    platform_filter: list[str]
    standard_refs: dict
    remediation_template_id: UUID | None = None
    source: str
    source_version: str | None = None
    is_enabled: bool
    status: str  # ACTIVE / DISABLED / REFERENCE_ONLY / DEPRECATED
    imported_at: datetime

    model_config = {"from_attributes": True}


ComplianceRuleListResponse = CursorPage[ComplianceRuleResponse]


class RemediationTemplateResponse(BaseModel):
    """The remediation for a rule: the provider, the command body, and the
    rollback. This is what would run on a host, so it is only handed to the
    roles that can act on one."""

    provider: str
    body: str
    rollback_body: str | None = None
    source: str = "complianceascode"
    version: int = 1


class PolicySetRuleRemediation(BaseModel):
    """One rule's remediation, as it applies inside a policy set."""

    rule_id: UUID
    rule_key: str
    title: str
    domain: str
    severity: str
    remediation: RemediationTemplateResponse | None = None


class FrameworkMapping(BaseModel):
    framework_key: str
    framework_name: str
    framework_version: str
    control_id: str
    control_title: str

class FailingAgent(BaseModel):
    agent_id: UUID
    hostname: str | None = None


class RuleDetailResponse(ComplianceRuleResponse):
    """Extends the catalog row (docs/compliance §37) with framework
    mappings, live coverage, and which agents are currently failing —
    everything a rule detail page needs in one call.

    `has_remediation` tells every role whether a remediation exists;
    `remediation` (the script and its rollback) is filled in only for the
    roles that can act on a host — the body is the command that would run
    there, not catalogue metadata."""

    framework_mappings: list[FrameworkMapping] = []
    coverage: dict[str, int] = {}
    failing_agents: list[FailingAgent] = []
    has_remediation: bool = False
    remediation: RemediationTemplateResponse | None = None


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
    status: str = "PUBLISHED"
    published_at: datetime | None = None
    published_version: int = 1
    parent_policy_set_id: UUID | None = None
    remediation: dict | None = None

    model_config = {"from_attributes": True}


PolicySetListResponse = CursorPage[PolicySetResponse]


class PolicySetRemediationUpdate(BaseModel):
    mode: str  # MONITOR | ASSISTED | AUTOMATIC
    allowed: list[str] = []
    forbidden: list[str] = []


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


class FacetValue(BaseModel):
    value: str
    count: int


class ComplianceDomain(BaseModel):
    """One domain of the canonical vocabulary, with how many rules exist for
    it and which report category it belongs to."""

    value: str
    rules: int = 0
    category: str = "configuration"


class ComplianceDomainsResponse(BaseModel):
    domains: list[ComplianceDomain] = []


class RuleFacetsResponse(BaseModel):
    """The distinct filter values the rule catalog actually has, with
    counts — so the catalog UI offers real choices instead of asking the
    operator to type a domain name correctly."""

    domains: list[FacetValue] = []
    severities: list[FacetValue] = []
    sources: list[FacetValue] = []
    platforms: list[FacetValue] = []
    frameworks: list[FacetValue] = []


class PolicyTemplateResponse(BaseModel):
    """A named selection over the rule catalog. rule_count and
    severity_breakdown are resolved against the live catalog so the picker
    can say "42 rules match" before anything is created."""

    key: str
    name: str
    description: str
    framework: str
    rule_count: int
    severity_breakdown: dict[str, int] = {}


class PolicySetFromTemplateRequest(BaseModel):
    """Create a policy set pre-populated from a template, in one call.

    name/slug/description default to the template's own values, so the
    common case is one field. include_unmapped adds reference-only rules
    (check_source != CEL) — they document coverage but produce no verdicts.
    severity_overrides re-maps a rule's severity *within this policy set*
    only (the rule's own severity is untouched), matching how CIS
    re-maps severity per profile.
    """

    template_key: str
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    version: str | None = None
    include_unmapped: bool = False
    severity_overrides: dict[str, str] = {}
    # Optional scope — creates the policy assignment in the same call so
    # "create and apply" is one action instead of three.
    scope_type: str | None = None
    scope_selector: dict[str, Any] = {}


class PolicySetFromTemplateResponse(BaseModel):
    policy_set: PolicySetResponse
    template_key: str
    rules_added: int
    severity_breakdown: dict[str, int] = {}
    assignment_id: UUID | None = None


class PolicySetProfileImportRequest(BaseModel):
    """Import a policy set from an exported profile (the artifact produced by
    GET /policy-sets/{id}/export). `profile` is the exported document; slug
    and name override the ones carried inside it."""

    profile: dict
    slug: str | None = None
    name: str | None = None


class PolicySetProfileImportResponse(BaseModel):
    policy_set: PolicySetResponse
    rules_imported: int
    missing_rules: list[str] = []


class PolicySetRemediationResponse(BaseModel):
    """Per-rule remediation for a policy set — the exact commands that would
    run on the hosts in scope. Empty when the set has no rule with a
    remediation."""

    policy_set_id: UUID
    remediations: list[PolicySetRuleRemediation] = []
