"""
LokiLinux — Workflow Pydantic schemas.

These models ARE the schema — GET /workflows/schema exports
WorkflowDocument.model_json_schema() verbatim for frontend autocomplete, so
there is exactly one authoritative definition of a valid workflow, not one
per language (plan §13).
"""

import re
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from lokilinux.schemas.common import CursorPage

_STEP_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
_WORKFLOW_NAME_RE = re.compile(r"^[a-z0-9-]{3,64}$")

# Config keys that must never carry a literal secret value — the workflow has
# no vault/credential store (plan §14); the only sanctioned path for a secret
# is the existing masked settings.SECRET_KEYS mechanism (settings_schema.py:73).
_SECRET_KEY_RE = re.compile(r"(password|passwd|secret|token|api_key|private_key)", re.IGNORECASE)


class WorkflowNodeType(str, Enum):
    """Partea III of the migration plan — 14 capability-based node types
    (plus 2 permanent legacy aliases) replacing the old use-case-shaped set.
    Grouped by palette category; the value strings are also what `type:`
    reads as in YAML, so keep them stable.

    VALIDATION and WAIT_FOR_AGENT are NOT removed and never will be —
    `workflow_versions.yaml_source` is immutable once PUBLISHED (see
    models/workflow.py's WorkflowVersion docstring), and the flagship
    `oracle-linux-8-to-9` workflow has 8 PUBLISHED `validation` steps. The
    engine (workflow_engine.py's `_normalize_type`) treats both aliases as
    the default variant of their replacement: VALIDATION behaves exactly
    like CHECK with `config.type` defaulted to `"command"` (which is what a
    validation step's flat `{command, expect_exit_code}` shape already is),
    and WAIT_FOR_AGENT behaves exactly like WAIT with `config.mode`
    defaulted to `"agent"`. No data migration needed — old rows just hit
    the default branch of the new, more general dispatch logic."""

    # Flow
    START = "start"
    END = "end"
    # Execution
    COMMAND = "command"
    ANSIBLE = "ansible"
    # Linux
    PACKAGE = "package"
    SERVICE = "service"
    FILE = "file"
    SYSTEM = "system"
    # Control
    CONDITION = "condition"
    APPROVAL = "approval"
    WAIT = "wait"
    # Validation
    CHECK = "check"
    # Integration
    NOTIFICATION = "notification"
    WEBHOOK = "webhook"
    # Legacy aliases — permanent, see class docstring
    VALIDATION = "validation"
    WAIT_FOR_AGENT = "wait_for_agent"


class TriggerType(str, Enum):
    MANUAL = "MANUAL"
    SCHEDULE = "SCHEDULE"


# ── spec.targets — same three shapes as PolicyTargetServers / resolve_targets ──

class WorkflowTargetFilters(BaseModel):
    os_family: str | None = None
    os_distro: str | None = None
    category_id: UUID | None = None
    project_id: UUID | None = None
    status: str | None = None


class WorkflowTargets(BaseModel):
    all: bool | None = None
    agent_ids: list[UUID] | None = None
    filters: WorkflowTargetFilters | None = None

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> "WorkflowTargets":
        shapes = [self.all is True, self.agent_ids is not None, self.filters is not None]
        if sum(shapes) != 1:
            raise ValueError("spec.targets must set exactly one of: all, agent_ids, filters")
        return self


class WorkflowStrategy(BaseModel):
    # v1 only accepts all_at_once — batch_size is accepted and validated so a
    # rolling/canary strategy never needs a schema migration later (plan §3).
    mode: str = "all_at_once"
    batch_size: int | None = Field(default=None, gt=0)

    @field_validator("mode")
    @classmethod
    def _supported_mode(cls, v: str) -> str:
        if v != "all_at_once":
            raise ValueError(f"strategy.mode '{v}' is not supported yet — only 'all_at_once' runs in this version")
        return v


class WorkflowDefaults(BaseModel):
    timeout: int | None = Field(default=None, gt=0)
    on_failure: str | None = None

    @field_validator("on_failure")
    @classmethod
    def _valid_on_failure(cls, v: str | None) -> str | None:
        if v is not None and v not in ("stop", "continue"):
            raise ValueError("defaults.on_failure must be 'stop' or 'continue'")
        return v


class StepRetry(BaseModel):
    attempts: int = Field(gt=0, le=10)
    delay: int = Field(ge=0)


class WorkflowStep(BaseModel):
    id: str
    type: WorkflowNodeType
    name: str
    config: dict = Field(default_factory=dict)
    disabled: bool = False
    timeout: int | None = Field(default=None, gt=0)
    retry: StepRetry | None = None
    on_failure: str | None = None  # stop / continue / branch

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not _STEP_ID_RE.match(v):
            raise ValueError(f"step id '{v}' must match ^[a-z0-9_-]{{1,64}}$")
        return v

    @field_validator("on_failure")
    @classmethod
    def _valid_on_failure(cls, v: str | None) -> str | None:
        if v is not None and v not in ("stop", "continue", "branch"):
            raise ValueError("step.on_failure must be 'stop', 'continue' or 'branch'")
        return v

    @model_validator(mode="after")
    def _no_literal_secrets(self) -> "WorkflowStep":
        for issue in _find_secret_literals(self.config, path=f"steps.{self.id}.config"):
            raise ValueError(issue)
        return self


def _find_secret_literals(value: object, path: str) -> list[str]:
    """Recursively flags string values on sensitive-looking keys — a nested
    dict (a future secret ref shape) is not a literal and is allowed through;
    only a bare string on a matching key is rejected."""
    issues: list[str] = []
    if isinstance(value, dict):
        for key, sub in value.items():
            sub_path = f"{path}.{key}"
            if _SECRET_KEY_RE.search(str(key)) and isinstance(sub, str) and sub:
                issues.append(f"{sub_path} looks like a literal secret — this workflow engine has no vault; use a settings-table secret reference instead")
            else:
                issues.extend(_find_secret_literals(sub, sub_path))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            issues.extend(_find_secret_literals(item, f"{path}[{i}]"))
    return issues


class WorkflowEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    on: str = "success"
    label: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("on")
    @classmethod
    def _valid_on(cls, v: str) -> str:
        if v not in ("success", "failure", "always"):
            raise ValueError("edge.on must be 'success', 'failure' or 'always'")
        return v


class WorkflowSpec(BaseModel):
    targets: WorkflowTargets
    strategy: WorkflowStrategy = Field(default_factory=WorkflowStrategy)
    defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)
    vars: dict = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=500)
    edges: list[WorkflowEdge] = Field(default_factory=list)


class WorkflowNodePosition(BaseModel):
    x: float
    y: float


class WorkflowMetadata(BaseModel):
    name: str
    description: str | None = None
    severity: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _WORKFLOW_NAME_RE.match(v):
            raise ValueError("metadata.name must match ^[a-z0-9-]{3,64}$")
        return v

    @field_validator("severity")
    @classmethod
    def _valid_severity(cls, v: str | None) -> str | None:
        if v is not None and v not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            raise ValueError("metadata.severity must be LOW, MEDIUM, HIGH or CRITICAL")
        return v


class WorkflowDocument(BaseModel):
    """The full YAML document, top to bottom — the authoritative shape."""

    apiVersion: str = "lokilinux/v1"
    kind: str = "Workflow"
    metadata: WorkflowMetadata
    spec: WorkflowSpec
    layout: dict[str, WorkflowNodePosition] = Field(default_factory=dict)

    @field_validator("apiVersion")
    @classmethod
    def _valid_api_version(cls, v: str) -> str:
        if v != "lokilinux/v1":
            raise ValueError("apiVersion must be 'lokilinux/v1'")
        return v

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, v: str) -> str:
        if v != "Workflow":
            raise ValueError("kind must be 'Workflow'")
        return v


# ── Validation results (compiler output) ────────────────────────────────────

class ValidationIssue(BaseModel):
    code: str
    message: str
    path: str
    line: int | None = None
    column: int | None = None
    step_id: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


# ── Compiled graph (workflow_versions.graph JSONB) ──────────────────────────

class CompiledGraph(BaseModel):
    """Normalized, validated form the engine reads — never re-parses YAML.

    Carries `layout` too (copied from WorkflowDocument.layout at compile
    time) purely so the frontend canvas has *something* to read back
    without a second round-trip — the engine itself never looks at it.
    Bundled into this same JSONB blob rather than a new column: no
    migration, and layout/graph are always written together anyway."""

    targets: WorkflowTargets
    strategy: WorkflowStrategy
    defaults: WorkflowDefaults
    vars: dict
    steps: list[WorkflowStep]
    edges: list[WorkflowEdge]
    entry_ids: list[str]  # steps with no incoming edge
    layout: dict[str, WorkflowNodePosition] = Field(default_factory=dict)


# ── API request/response shapes ─────────────────────────────────────────────

class WorkflowValidateRequest(BaseModel):
    yaml: str


class WorkflowCreate(BaseModel):
    name: str
    yaml: str


class WorkflowUpdate(BaseModel):
    name: str | None = None
    is_enabled: bool | None = None
    trigger_type: TriggerType | None = None
    cron_expr: str | None = None
    priority: int | None = None
    tags: list[str] | None = None


class WorkflowVersionCreate(BaseModel):
    yaml: str
    base_content_hash: str | None = None  # required when updating a DRAFT — 409 on mismatch


class WorkflowRunRequest(BaseModel):
    is_dry_run: bool = False


class WorkflowResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    is_enabled: bool
    current_version_id: UUID | None
    trigger_type: TriggerType
    cron_expr: str | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    priority: int
    severity: str | None
    tags: list[str]
    migrated_from_policy_id: UUID | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


WorkflowListResponse = CursorPage[WorkflowResponse]


class WorkflowVersionResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    version: int
    yaml_source: str
    # Already computed and stored at create/publish time (workflow_compiler.py) —
    # serialized here so the canvas (frontend) never has to re-parse YAML just
    # to render nodes/edges. The comment-preserving surgical edit path (plan
    # §9) still reads/writes yaml_source directly; this field is read-only.
    graph: dict
    content_hash: str
    status: str
    change_summary: str | None
    created_by: UUID | None
    created_at: datetime
    published_at: datetime | None

    model_config = {"from_attributes": True}


WorkflowVersionListResponse = CursorPage[WorkflowVersionResponse]


class WorkflowDetailResponse(WorkflowResponse):
    current_version: WorkflowVersionResponse | None = None


class WorkflowRunResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    status: str
    trigger_type: str
    triggered_by: UUID | None
    targets: dict
    vars: dict
    is_dry_run: bool
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


WorkflowRunListResponse = CursorPage[WorkflowRunResponse]


class WorkflowStepRunResponse(BaseModel):
    id: UUID
    run_id: UUID
    step_id: str
    status: str
    attempt: int
    job_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    output: dict | None
    error: str | None

    model_config = {"from_attributes": True}


class WorkflowRunDetailResponse(WorkflowRunResponse):
    step_runs: list[WorkflowStepRunResponse] = Field(default_factory=list)


class DryRunStepResult(BaseModel):
    id: str
    type: str
    eligible: int
    blocked: int
    reasons: dict[str, int] = Field(default_factory=dict)


class DryRunResponse(BaseModel):
    targets_matched: int
    targets: list[UUID]
    steps: list[DryRunStepResult]
    estimated_dispatch_seconds: int
    requires_approval_at: list[str]
