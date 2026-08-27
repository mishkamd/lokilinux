"""
LokiLinux — Compliance: Policy Engine router.

Rule catalog is read-only except for /policy-sets/import, which pulls
content from ComplianceAsCode (docs/compliance/07-POLICY-ENGINE.md) — see
services/complianceascode_importer.py for why that means "fetch an XCCDF
datastream", not "clone the git repo". Policy sets and assignments are full
CRUD, matching the simple create/list pattern in routers/policies.py rather
than the multi-stage approval workflow baselines use — a policy set is a
lower-stakes, easily-reversible grouping, not a signed, fleet-wide contract.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import String, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_permission, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.models.compliance_rule import (
    ComplianceRule,
    PolicyAssignment,
    PolicySet,
    PolicySetRule,
    RemediationTemplate,
)
from lokilinux.models.job import Job, JobStatus
from lokilinux.models.rule_evaluation import RuleEvaluation
from lokilinux.api.v1.routers.compliance._pagination import paginate_keyset
from lokilinux.schemas.common import CursorPage
from lokilinux.schemas.compliance_rule import (
    ComplianceRuleResponse,
    FailingAgent,
    FrameworkMapping,
    PolicyAssignmentCreate,
    PolicyAssignmentResponse,
    PolicySetCoverageResponse,
    PolicySetCreate,
    PolicySetImportRequest,
    PolicySetImportResponse,
    PolicySetRemediationUpdate,
    PolicySetResponse,
    PolicySetRuleAdd,
    RemediationTemplateResponse,
    RuleCoverageResponse,
    RuleDetailResponse,
)
from lokilinux.services.audit_service import AuditService
from lokilinux.services.complianceascode_importer import ComplianceAsCodeImporter
from lokilinux.services.policy_set_service import PolicySetService

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Rule catalog (read-only) ──────────────────────────────────────────────────


def _apply_rule_filters(q, search, severity, domain, framework, platform, source, status, check_source):
    """Shared WHERE-clause builder for list_rules' item query and its count
    query — kept as one function so the two can never drift apart
    (docs/compliance §18: Rule Catalog filters on domain/severity/platform/
    framework/source/status, search across rule ID/name/description/CCE/
    NIST/STIG/CIS/PCI-DSS)."""
    if search:
        pattern = f"%{search}%"
        q = q.where(
            ComplianceRule.title.ilike(pattern)
            | ComplianceRule.rule_key.ilike(pattern)
            | ComplianceRule.description.ilike(pattern)
            | ComplianceRule.standard_refs.cast(String).ilike(pattern)
        )
    if severity:
        q = q.where(ComplianceRule.severity == severity)
    if domain:
        q = q.where(ComplianceRule.domain == domain)
    if framework:
        q = q.where(ComplianceRule.standard_refs.has_key(framework))
    if platform:
        q = q.where(ComplianceRule.platform_filter.contains([platform]))
    if source:
        q = q.where(ComplianceRule.source == source)
    if check_source:
        q = q.where(ComplianceRule.check_source == check_source)
    if status == "enabled":
        q = q.where(ComplianceRule.is_enabled.is_(True))
    elif status == "disabled":
        q = q.where(ComplianceRule.is_enabled.is_(False))
    return q


@router.get("/rules", response_model=CursorPage[ComplianceRuleResponse])
async def list_rules(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(
        None, description="Matches rule key, title, description, or any standard_refs value (CCE/NIST/STIG/CIS/PCI-DSS)"
    ),
    severity: str | None = Query(None),
    domain: str | None = Query(None),
    framework: str | None = Query(
        None, description="Filters via standard_refs JSONB key presence, e.g. 'cis'"
    ),
    platform: str | None = Query(None, description="e.g. 'rocky9' — matches compliance_rules.platform_filter"),
    source: str | None = Query(None, description="e.g. 'complianceascode'"),
    status: str | None = Query(None, description="'enabled' or 'disabled'"),
    check_source: str | None = Query(None, description="CEL / OVAL_UNMAPPED / OSCAP_FALLBACK"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[ComplianceRuleResponse]:
    q = select(ComplianceRule).order_by(ComplianceRule.imported_at.desc(), ComplianceRule.id.desc())
    q = _apply_rule_filters(q, search, severity, domain, framework, platform, source, status, check_source)

    items, next_cursor = await paginate_keyset(
        db, q,
        ts_col=ComplianceRule.imported_at, tie_col=ComplianceRule.id,
        cursor=cursor, limit=limit,
        ts_attr="imported_at",
        scalars=True,
    )

    # total count (no cursor filter — lightweight approximate, mirrors servers.py)
    count_q = _apply_rule_filters(
        select(func.count()).select_from(ComplianceRule),
        search, severity, domain, framework, platform, source, status, check_source,
    )
    total = (await db.execute(count_q)).scalar()

    return CursorPage[ComplianceRuleResponse](
        items=[ComplianceRuleResponse.model_validate(r) for r in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/rules/{rule_id}", response_model=RuleDetailResponse)
async def get_rule_detail(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> RuleDetailResponse:
    """Full rule detail (docs/compliance §37): everything list_rules already
    returns, plus framework mappings (the normalized Framework/Control
    tables, not just raw standard_refs), live PASS/FAIL/NOT_APPLICABLE/
    ERROR coverage from the latest verdict per agent, and which agents are
    currently failing."""
    rule = (await db.execute(select(ComplianceRule).where(ComplianceRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")

    mapping_rows = (
        await db.execute(
            text(
                """
                SELECT f.key, f.name, fv.version, c.control_id, c.title
                FROM compliance_rule_mappings rm
                JOIN compliance_controls c ON c.id = rm.control_id
                JOIN compliance_framework_versions fv ON fv.id = c.framework_version_id
                JOIN compliance_frameworks f ON f.id = fv.framework_id
                WHERE rm.rule_id = :rule_id
                ORDER BY f.key, fv.version
                """
            ),
            {"rule_id": rule_id},
        )
    ).mappings().all()
    framework_mappings = [
        FrameworkMapping(
            framework_key=m["key"], framework_name=m["name"], framework_version=m["version"],
            control_id=m["control_id"], control_title=m["title"],
        )
        for m in mapping_rows
    ]

    coverage_rows = (
        await db.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (agent_id) agent_id, result
                    FROM rule_evaluations WHERE rule_id = :rule_id
                    ORDER BY agent_id, time DESC
                )
                SELECT result, count(*) AS n FROM latest GROUP BY result
                """
            ),
            {"rule_id": rule_id},
        )
    ).mappings().all()
    coverage = {"PASS": 0, "FAIL": 0, "NOT_APPLICABLE": 0, "ERROR": 0, "NOT_EVALUATED": 0}
    for r in coverage_rows:
        coverage[r["result"]] = r["n"]

    failing_rows = (
        await db.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (agent_id) agent_id, result
                    FROM rule_evaluations WHERE rule_id = :rule_id
                    ORDER BY agent_id, time DESC
                )
                SELECT latest.agent_id, agents.hostname
                FROM latest
                LEFT JOIN agents ON agents.id = latest.agent_id
                WHERE latest.result = 'FAIL' LIMIT 50
                """
            ),
            {"rule_id": rule_id},
        )
    ).mappings().all()
    failing_agents = [FailingAgent(agent_id=r["agent_id"], hostname=r["hostname"]) for r in failing_rows]

    return RuleDetailResponse(
        **ComplianceRuleResponse.model_validate(rule).model_dump(),
        framework_mappings=framework_mappings,
        coverage=coverage,
        failing_agents=failing_agents,
    )


@router.get("/rules/{rule_id}/coverage", response_model=RuleCoverageResponse)
async def get_rule_coverage(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> RuleCoverageResponse:
    rule = (
        await db.execute(select(ComplianceRule).where(ComplianceRule.id == rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")

    evaluated_count = (
        await db.execute(
            select(func.count(func.distinct(RuleEvaluation.agent_id))).where(
                RuleEvaluation.rule_id == rule_id
            )
        )
    ).scalar_one()

    return RuleCoverageResponse(
        rule_id=rule.id,
        rule_key=rule.rule_key,
        check_source=rule.check_source,
        evaluated_agent_count=evaluated_count,
    )


@router.get(
    "/rules/{rule_id}/remediation-templates", response_model=list[RemediationTemplateResponse]
)
async def list_remediation_templates(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[RemediationTemplateResponse]:
    rule = (
        await db.execute(select(ComplianceRule).where(ComplianceRule.id == rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    rows = (
        (
            await db.execute(
                select(RemediationTemplate).where(RemediationTemplate.rule_key == rule.rule_key)
            )
        )
        .scalars()
        .all()
    )
    return [RemediationTemplateResponse.model_validate(t) for t in rows]


# ── Policy sets ────────────────────────────────────────────────────────────────


@router.get("/policy-sets", response_model=CursorPage[PolicySetResponse])
async def list_policy_sets(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    framework: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[PolicySetResponse]:
    q = select(PolicySet).order_by(PolicySet.created_at.desc(), PolicySet.id.desc())
    if framework:
        q = q.where(PolicySet.framework == framework)
    items, next_cursor = await paginate_keyset(
        db, q,
        ts_col=PolicySet.created_at, tie_col=PolicySet.id,
        cursor=cursor, limit=limit,
        scalars=True,
    )
    # total count (no cursor filter — lightweight approximate, mirrors servers.py)
    count_q = select(func.count()).select_from(PolicySet)
    if framework:
        count_q = count_q.where(PolicySet.framework == framework)
    total = (await db.execute(count_q)).scalar()

    return CursorPage[PolicySetResponse](
        items=[PolicySetResponse.model_validate(p) for p in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("/policy-sets", response_model=PolicySetResponse, status_code=201)
async def create_policy_set(
    body: PolicySetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.policies.manage")),
) -> PolicySetResponse:
    """Creates a DRAFT policy set (docs/compliance §6) — add rules via
    POST .../rules, then POST .../publish to make it live. is_enabled stays
    false until published, so an in-progress draft is never picked up by
    policy resolution."""
    policy_set = await PolicySetService(db).create_draft(
        name=body.name, slug=body.slug, framework=body.framework,
        version=body.version, description=body.description,
    )
    await AuditService(db).log(
        action="compliance.policy_set_created",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="policy_set",
        resource_id=str(policy_set.id),
        changes={"name": body.name, "slug": body.slug, "framework": body.framework},
    )
    return PolicySetResponse.model_validate(policy_set)


@router.post("/policy-sets/{policy_set_id}/publish", response_model=PolicySetResponse)
async def publish_policy_set(
    policy_set_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.policies.manage")),
) -> PolicySetResponse:
    policy_set = await PolicySetService(db).publish(policy_set_id, current_user)
    return PolicySetResponse.model_validate(policy_set)


@router.post("/policy-sets/{policy_set_id}/archive", response_model=PolicySetResponse)
async def archive_policy_set(
    policy_set_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.policies.archive")),
) -> PolicySetResponse:
    policy_set = await PolicySetService(db).archive(policy_set_id, current_user)
    return PolicySetResponse.model_validate(policy_set)


@router.post("/policy-sets/{policy_set_id}/new-version", response_model=PolicySetResponse, status_code=201)
async def new_policy_set_version(
    policy_set_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.policies.manage")),
) -> PolicySetResponse:
    """Clones a PUBLISHED policy set's rules into a new DRAFT — the
    published row is never mutated, matching baselines' immutable-once-
    published rule. Edit the returned draft's rules, then publish it."""
    clone = await PolicySetService(db).create_new_version(policy_set_id, current_user)
    return PolicySetResponse.model_validate(clone)


@router.patch("/policy-sets/{policy_set_id}/remediation", response_model=PolicySetResponse)
async def set_policy_set_remediation(
    policy_set_id: UUID,
    body: PolicySetRemediationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.policies.manage")),
) -> PolicySetResponse:
    """Sets this policy's remediation mode (plan U7/KTD8) — NULL/unset means
    ASSISTED, the pre-U7 behavior. AUTOMATIC additionally requires the
    global compliance.auto_remediation_enabled kill-switch; this endpoint
    only configures the policy-level allowlist, it never flips that switch."""
    if body.mode not in ("MONITOR", "ASSISTED", "AUTOMATIC"):
        raise HTTPException(status_code=422, detail="mode must be MONITOR, ASSISTED, or AUTOMATIC")
    policy_set = await db.get(PolicySet, policy_set_id)
    if policy_set is None:
        raise HTTPException(status_code=404, detail="Policy set not found")

    policy_set.remediation = {
        "mode": body.mode,
        "allowed": body.allowed,
        "forbidden": body.forbidden,
    }
    await db.commit()

    await AuditService(db).log(
        action="compliance.policy_set_remediation_updated",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="policy_set",
        resource_id=str(policy_set_id),
        changes=policy_set.remediation,
    )
    return PolicySetResponse.model_validate(policy_set)


@router.post("/policy-sets/import", response_model=PolicySetImportResponse, status_code=202)
async def import_policy_set(
    body: PolicySetImportRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.policies.import")),
) -> PolicySetImportResponse:
    """Fetches body.datastream_url, parses it as an XCCDF 1.2 datastream,
    and upserts compliance_rules/policy_sets/policy_set_rules — see
    services/complianceascode_importer.py. Runs as a background task (a
    real content import is thousands of rules, too slow for a synchronous
    request) tracked via a Job row so it shows up in job history like any
    other long-running operation; it never dispatches to an agent
    (target_servers stays empty) since this work runs on the control plane.
    """
    job = Job(
        name=f"Import {body.source} content {body.content_version}",
        job_type="COMPLIANCE_IMPORT_CONTENT",
        parameters={
            "source": body.source,
            "profile_id": body.profile_id,
            "content_version": body.content_version,
            "datastream_url": body.datastream_url,
        },
        status=JobStatus.QUEUED,
        created_by=safe_user_uuid(current_user),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    session_factory = request.app.state.session_factory
    selected_profile_ids = [body.profile_id] if body.profile_id else None
    background_tasks.add_task(
        _run_compliance_import,
        session_factory,
        job.id,
        body.datastream_url,
        body.content_version,
        selected_profile_ids,
    )

    return PolicySetImportResponse(job_id=job.id, status=JobStatus.QUEUED.value)


async def _run_compliance_import(
    session_factory,
    job_id: UUID,
    datastream_url: str,
    content_version: str,
    selected_profile_ids: list[str] | None,
) -> None:
    async with session_factory() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
        if job is None:
            logger.error("compliance import job %s vanished before it could run", job_id)
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(datastream_url)
                resp.raise_for_status()
                xml_bytes = resp.content

            result = await ComplianceAsCodeImporter(db).import_datastream(
                xml_bytes, content_version, selected_profile_ids
            )

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.parameters = {
                **(job.parameters or {}),
                "result": {
                    "rules_imported": result.rules_imported,
                    "rules_updated": result.rules_updated,
                    "policy_sets_imported": result.policy_sets_imported,
                    "rules_added": result.rules_added,
                    "rules_modified": result.rules_modified,
                    "rules_unchanged": result.rules_unchanged,
                    "rules_removed": result.rules_removed,
                },
            }
            await db.commit()
        except Exception as exc:
            logger.error("compliance content import failed", exc_info=True)
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            job.parameters = {**(job.parameters or {}), "error": str(exc)}
            await db.commit()


@router.get("/policy-sets/{policy_set_id}", response_model=PolicySetResponse)
async def get_policy_set(
    policy_set_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> PolicySetResponse:
    row = (
        await db.execute(select(PolicySet).where(PolicySet.id == policy_set_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy set not found")
    return PolicySetResponse.model_validate(row)


@router.get("/policy-sets/{policy_set_id}/rules", response_model=list[ComplianceRuleResponse])
async def list_policy_set_rules(
    policy_set_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[ComplianceRuleResponse]:
    rows = (
        (
            await db.execute(
                select(ComplianceRule)
                .join(PolicySetRule, PolicySetRule.rule_id == ComplianceRule.id)
                .where(PolicySetRule.policy_set_id == policy_set_id)
            )
        )
        .scalars()
        .all()
    )
    return [ComplianceRuleResponse.model_validate(r) for r in rows]


@router.post("/policy-sets/{policy_set_id}/rules", status_code=201)
async def add_policy_set_rule(
    policy_set_id: UUID,
    body: PolicySetRuleAdd,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.policies.manage")),
) -> dict:
    policy_set = (
        await db.execute(select(PolicySet).where(PolicySet.id == policy_set_id))
    ).scalar_one_or_none()
    if policy_set is None:
        raise HTTPException(status_code=404, detail="Policy set not found")
    rule = (
        await db.execute(select(ComplianceRule).where(ComplianceRule.id == body.rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")

    existing = (
        await db.execute(
            select(PolicySetRule).where(
                PolicySetRule.policy_set_id == policy_set_id, PolicySetRule.rule_id == body.rule_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            PolicySetRule(
                policy_set_id=policy_set_id,
                rule_id=body.rule_id,
                severity_override=body.severity_override,
            )
        )
        await db.commit()
        await AuditService(db).log(
            action="compliance.policy_set_rule_added",
            user_id=current_user.get("id"),
            actor_name=current_user.get("username") or current_user.get("email"),
            resource_type="policy_set",
            resource_id=str(policy_set_id),
            changes={
                "rule_id": str(body.rule_id),
                "rule_key": rule.rule_key,
                "severity_override": body.severity_override,
            },
        )
    return {"policy_set_id": str(policy_set_id), "rule_id": str(body.rule_id), "status": "added"}


@router.get("/policy-sets/{policy_set_id}/coverage", response_model=PolicySetCoverageResponse)
async def get_policy_set_coverage(
    policy_set_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> PolicySetCoverageResponse:
    policy_set = (
        await db.execute(select(PolicySet).where(PolicySet.id == policy_set_id))
    ).scalar_one_or_none()
    if policy_set is None:
        raise HTTPException(status_code=404, detail="Policy set not found")

    mapped = (
        await db.execute(
            select(func.count())
            .select_from(PolicySetRule)
            .join(ComplianceRule, ComplianceRule.id == PolicySetRule.rule_id)
            .where(
                PolicySetRule.policy_set_id == policy_set_id, ComplianceRule.check_source == "CEL"
            )
        )
    ).scalar_one()
    total = (
        await db.execute(
            select(func.count())
            .select_from(PolicySetRule)
            .where(PolicySetRule.policy_set_id == policy_set_id)
        )
    ).scalar_one()
    unmapped = total - mapped
    coverage_pct = round(100.0 * mapped / total, 1) if total else 0.0

    return PolicySetCoverageResponse(
        policy_set_id=policy_set_id,
        mapped=mapped,
        unmapped=unmapped,
        coverage_pct=coverage_pct,
    )


# ── Policy assignments ─────────────────────────────────────────────────────────


@router.get("/policy-assignments", response_model=list[PolicyAssignmentResponse])
async def list_policy_assignments(
    scope_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[PolicyAssignmentResponse]:
    q = select(PolicyAssignment).order_by(PolicyAssignment.created_at.desc())
    if scope_type:
        q = q.where(PolicyAssignment.scope_type == scope_type)
    rows = (await db.execute(q)).scalars().all()
    return [PolicyAssignmentResponse.model_validate(a) for a in rows]


@router.post("/policy-assignments", response_model=PolicyAssignmentResponse, status_code=201)
async def create_policy_assignment(
    body: PolicyAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.policies.manage")),
) -> PolicyAssignmentResponse:
    policy_set = (
        await db.execute(select(PolicySet).where(PolicySet.id == body.policy_set_id))
    ).scalar_one_or_none()
    if policy_set is None:
        raise HTTPException(status_code=404, detail="Policy set not found")
    assignment = PolicyAssignment(
        policy_set_id=body.policy_set_id,
        scope_type=body.scope_type,
        scope_selector=body.scope_selector,
        created_by=safe_user_uuid(current_user),
    )
    db.add(assignment)
    await db.commit()
    await AuditService(db).log(
        action="compliance.policy_assignment_created",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="policy_assignment",
        resource_id=str(assignment.id),
        changes={
            "policy_set_id": str(body.policy_set_id),
            "scope_type": body.scope_type,
            "scope_selector": body.scope_selector,
        },
    )
    return PolicyAssignmentResponse.model_validate(assignment)
