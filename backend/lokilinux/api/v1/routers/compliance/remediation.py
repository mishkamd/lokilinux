"""
LokiLinux — Compliance: Remediation Engine router.

Approval creates a real Job through the existing JobService — see
services/remediation_service.py for why plan-approval and Job creation
happen atomically rather than as two separate steps.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.cache import RedisCache
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.models.remediation import RemediationAction, RemediationPlan
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.remediation import (
    RemediationActionResponse,
    RemediationPlanCreate,
    RemediationPlanResponse,
)
from lokilinux.services.job_service import JobService
from lokilinux.services.remediation_service import RemediationService

router = APIRouter()


@router.get("/remediation-plans", response_model=CursorPage[RemediationPlanResponse])
async def list_remediation_plans(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    status_: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[RemediationPlanResponse]:
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
        name=body.name, trigger_type=body.trigger_type.value, actions=body.actions,
        is_emergency=body.is_emergency, created_by=safe_user_uuid(current_user),
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
            select(RemediationAction)
            .where(RemediationAction.remediation_plan_id == plan_id)
            .order_by(RemediationAction.sequence)
        )
    ).scalars().all()
    return [RemediationActionResponse.model_validate(a) for a in rows]


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
