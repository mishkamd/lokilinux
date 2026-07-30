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
from datetime import datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
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
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.compliance_rule import (
    ComplianceRuleResponse,
    PolicyAssignmentCreate,
    PolicyAssignmentResponse,
    PolicySetCoverageResponse,
    PolicySetCreate,
    PolicySetImportRequest,
    PolicySetImportResponse,
    PolicySetResponse,
    PolicySetRuleAdd,
    RemediationTemplateResponse,
    RuleCoverageResponse,
)
from lokilinux.services.audit_service import AuditService
from lokilinux.services.complianceascode_importer import ComplianceAsCodeImporter

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Rule catalog (read-only) ──────────────────────────────────────────────────


@router.get("/rules", response_model=CursorPage[ComplianceRuleResponse])
async def list_rules(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    severity: str | None = Query(None),
    domain: str | None = Query(None),
    framework: str | None = Query(
        None, description="Filters via standard_refs JSONB key presence, e.g. 'cis'"
    ),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[ComplianceRuleResponse]:
    q = select(ComplianceRule).order_by(ComplianceRule.imported_at.desc(), ComplianceRule.id.desc())
    if search:
        q = q.where(ComplianceRule.title.ilike(f"%{search}%"))
    if severity:
        q = q.where(ComplianceRule.severity == severity)
    if domain:
        q = q.where(ComplianceRule.domain == domain)
    if framework:
        q = q.where(ComplianceRule.standard_refs.has_key(framework))

    if cursor:
        raw = decode_cursor(cursor)
        ts_str, rid = raw.rsplit(":", 1)
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (ComplianceRule.imported_at < ts)
            | ((ComplianceRule.imported_at == ts) & (ComplianceRule.id < UUID(rid)))
        )

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.imported_at.isoformat()}:{last.id}")

    return CursorPage[ComplianceRuleResponse](
        items=[ComplianceRuleResponse.model_validate(r) for r in items],
        next_cursor=next_cursor,
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
    if cursor:
        raw = decode_cursor(cursor)
        ts_str, pid = raw.rsplit(":", 1)
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (PolicySet.created_at < ts)
            | ((PolicySet.created_at == ts) & (PolicySet.id < UUID(pid)))
        )
    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")
    return CursorPage[PolicySetResponse](
        items=[PolicySetResponse.model_validate(p) for p in items],
        next_cursor=next_cursor,
    )


@router.post("/policy-sets", response_model=PolicySetResponse, status_code=201)
async def create_policy_set(
    body: PolicySetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PolicySetResponse:
    existing = (
        await db.execute(select(PolicySet).where(PolicySet.slug == body.slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Policy set slug '{body.slug}' already exists")
    policy_set = PolicySet(
        name=body.name,
        slug=body.slug,
        framework=body.framework,
        version=body.version,
        description=body.description,
    )
    db.add(policy_set)
    await db.commit()
    await AuditService(db).log(
        action="compliance.policy_set_created",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="policy_set",
        resource_id=str(policy_set.id),
        changes={"name": body.name, "slug": body.slug, "framework": body.framework},
    )
    return PolicySetResponse.model_validate(policy_set)


@router.post("/policy-sets/import", response_model=PolicySetImportResponse, status_code=202)
async def import_policy_set(
    body: PolicySetImportRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN")),
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
        created_by=safe_user_uuid(current_user.get("id")),
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
        job.started_at = datetime.utcnow()
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
            job.completed_at = datetime.utcnow()
            job.parameters = {
                **(job.parameters or {}),
                "result": {
                    "rules_imported": result.rules_imported,
                    "rules_updated": result.rules_updated,
                    "policy_sets_imported": result.policy_sets_imported,
                },
            }
            await db.commit()
        except Exception as exc:
            logger.error("compliance content import failed", exc_info=True)
            job.status = JobStatus.FAILED
            job.completed_at = datetime.utcnow()
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
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
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
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
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
