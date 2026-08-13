"""
LokiLinux — Compliance Remediation API routes.
"""

from datetime import datetime
from uuid import UUID

import zoneinfo
from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.cache import RedisCache
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.models.agent import Agent
from lokilinux.models.job import Job, JobResult
from lokilinux.models.remediation import (
    MaintenanceWindow,
    RemediationAction,
    RemediationJob,
    RemediationPlan,
)
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.remediation import (
    MaintenanceWindowCreate,
    MaintenanceWindowResponse,
    RemediationActionResponse,
    RemediationExecutionResponse,
    RemediationExecutionResult,
    RemediationPlanCreate,
    RemediationPlanResponse,
)
from lokilinux.services.job_service import JobService
from lokilinux.services.remediation_service import RemediationService

router = APIRouter()

_VALID_SCOPE_TYPES = {"GLOBAL", "OS", "ROLE", "ENVIRONMENT", "DATACENTER", "CLUSTER", "APPLICATION"}


# ── Maintenance Windows ──────────────────────────────────────────────────────


@router.get("/maintenance-windows", response_model=list[MaintenanceWindowResponse])
async def list_maintenance_windows(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[MaintenanceWindowResponse]:
    rows = (
        await db.execute(select(MaintenanceWindow).order_by(MaintenanceWindow.name))
    ).scalars().all()
    return [MaintenanceWindowResponse.model_validate(w) for w in rows]


@router.post("/maintenance-windows", response_model=MaintenanceWindowResponse, status_code=201)
async def create_maintenance_window(
    body: MaintenanceWindowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> MaintenanceWindowResponse:
    # Validate timezone
    try:
        zoneinfo.ZoneInfo(body.timezone)
    except (KeyError, Exception) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid timezone: {body.timezone}") from exc

    # Validate cron expression
    if body.cron_expr is not None:
        try:
            croniter(body.cron_expr)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid cron expression: {body.cron_expr}") from exc

    # Validate scope_type
    if body.scope_type not in _VALID_SCOPE_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid scope_type: {body.scope_type}")

    window = MaintenanceWindow(
        name=body.name,
        scope_type=body.scope_type,
        scope_selector=body.scope_selector,
        cron_expr=body.cron_expr,
        duration_minutes=body.duration_minutes,
        timezone=body.timezone,
        is_enabled=body.is_enabled,
    )
    db.add(window)
    await db.commit()
    return MaintenanceWindowResponse.model_validate(window)


# ── Remediation Plans ────────────────────────────────────────────────────────


@router.get("/remediation-plans", response_model=CursorPage[RemediationPlanResponse])
async def list_remediation_plans(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    status_: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[RemediationPlanResponse]:
    # Total count with same filters (no cursor filter)
    count_q = select(func.count()).select_from(RemediationPlan)
    if status_:
        count_q = count_q.where(RemediationPlan.status == status_)
    total = (await db.execute(count_q)).scalar() or 0

    q = select(RemediationPlan).order_by(RemediationPlan.created_at.desc(), RemediationPlan.id.desc())
    if status_:
        q = q.where(RemediationPlan.status == status_)
    if cursor:
        raw = decode_cursor(cursor)
        ts_str, pid = raw.rsplit(":", 1)
        ts = datetime.fromisoformat(ts_str)
        q = q.where((RemediationPlan.created_at < ts) | ((RemediationPlan.created_at == ts) & (RemediationPlan.id < UUID(pid))))
    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")
    return CursorPage[RemediationPlanResponse](
        items=[RemediationPlanResponse.model_validate(p) for p in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("/remediation-plans", response_model=RemediationPlanResponse, status_code=201)
async def create_remediation_plan(
    body: RemediationPlanCreate,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> RemediationPlanResponse:
    svc = RemediationService(db, JobService(db, cache, nats))
    plan = await svc.create_plan(
        name=body.name,
        trigger_type=body.trigger_type.value,
        actions=body.actions,
        is_emergency=body.is_emergency,
        maintenance_window_id=body.maintenance_window_id,
        created_by=safe_user_uuid(current_user),
    )
    return RemediationPlanResponse.model_validate(plan)


@router.get("/remediation-plans/{plan_id}", response_model=RemediationPlanResponse)
async def get_remediation_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> RemediationPlanResponse:
    row = (await db.execute(select(RemediationPlan).where(RemediationPlan.id == plan_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Remediation plan not found")
    return RemediationPlanResponse.model_validate(row)


@router.get("/remediation-plans/{plan_id}/actions", response_model=list[RemediationActionResponse])
async def list_remediation_actions(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[RemediationActionResponse]:
    rows = (
        await db.execute(
            select(RemediationAction, Agent.hostname)
            .outerjoin(Agent, Agent.id == RemediationAction.agent_id)
            .where(RemediationAction.remediation_plan_id == plan_id)
            .order_by(RemediationAction.sequence)
        )
    ).all()
    return [
        RemediationActionResponse.model_validate(a).model_copy(update={"hostname": hostname})
        for a, hostname in rows
    ]


@router.post("/remediation-plans/{plan_id}/submit", response_model=RemediationPlanResponse)
async def submit_remediation_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> RemediationPlanResponse:
    svc = RemediationService(db, JobService(db, cache, nats))
    plan = await svc.submit(plan_id, current_user)
    return RemediationPlanResponse.model_validate(plan)


@router.post("/remediation-plans/{plan_id}/dry-run", response_model=RemediationPlanResponse, status_code=202)
async def dry_run_remediation_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> RemediationPlanResponse:
    """Runs each action's real check mode (ansible --check --diff, sh -n,
    Python ast.parse) without applying anything. Poll GET
    .../execution afterwards for results — the plan's own status is
    untouched (docs/compliance §13)."""
    svc = RemediationService(db, JobService(db, cache, nats))
    plan = await svc.dry_run(plan_id, current_user)
    return RemediationPlanResponse.model_validate(plan)


@router.post("/remediation-plans/{plan_id}/approve", response_model=RemediationPlanResponse)
async def approve_remediation_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> RemediationPlanResponse:
    svc = RemediationService(db, JobService(db, cache, nats))
    plan = await svc.approve(plan_id, current_user)
    return RemediationPlanResponse.model_validate(plan)


# ── Execution & Rollback ─────────────────────────────────────────────────────


@router.get("/remediation-plans/{plan_id}/execution", response_model=RemediationExecutionResponse)
async def get_remediation_execution(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> RemediationExecutionResponse:
    """Return the most recent Job and its results for a remediation plan."""
    # Check plan exists
    plan = (await db.execute(
        select(RemediationPlan).where(RemediationPlan.id == plan_id)
    )).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Remediation plan not found")

    # Find the most recent linked job
    link = (
        await db.execute(
            select(RemediationJob)
            .join(Job, Job.id == RemediationJob.job_id)
            .where(RemediationJob.remediation_plan_id == plan_id)
            .order_by(Job.created_at.desc())
        )
    ).scalars().first()

    if link is None:
        return RemediationExecutionResponse(job_id=None, operation=None, job_status=None, results=[])

    job = await db.get(Job, link.job_id)
    operation = (job.parameters or {}).get("operation")
    if operation not in ("APPLY", "ROLLBACK", "DRY_RUN"):
        operation = None

    # Get results
    results = (
        await db.execute(
            select(JobResult).where(JobResult.job_id == job.id)
        )
    ).scalars().all()

    return RemediationExecutionResponse(
        job_id=job.id,
        operation=operation,
        job_status=job.status,
        results=[
            RemediationExecutionResult(
                agent_id=r.agent_id,
                status=r.status,
                exit_code=r.exit_code,
                error_message=r.error_message,
                stdout=r.stdout,
                stderr=r.stderr,
                duration_seconds=r.duration_seconds,
            )
            for r in results
        ],
    )


@router.post("/remediation-plans/{plan_id}/rollback", response_model=RemediationPlanResponse)
async def rollback_remediation_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN")),
) -> RemediationPlanResponse:
    svc = RemediationService(db, JobService(db, cache, nats))
    plan = await svc.rollback(plan_id, current_user)
    return RemediationPlanResponse.model_validate(plan)
