"""
LokiLinux — Compliance: Exceptions/Waivers router (docs/compliance §17).

CRUD + approve/revoke. Every mutation writes an audit log entry
(ExceptionService), matching the module-wide rule (§26) that policy,
baseline, and exception changes are all audited. Expiry itself is a
background job (services/compliance/internal/scheduler.Expirer), not an
endpoint — there's nothing for a client to call to make time pass.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_permission, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.models.agent import Agent
from lokilinux.models.compliance_exception import ComplianceException
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.api.v1.routers.compliance._pagination import paginate_keyset
from lokilinux.schemas.common import CursorPage
from lokilinux.schemas.compliance_exception import ExceptionCreate, ExceptionResponse
from lokilinux.services.compliance_exception_service import ExceptionService

router = APIRouter()


@router.get("/exceptions", response_model=CursorPage[ExceptionResponse])
async def list_exceptions(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    rule_id: UUID | None = Query(None),
    agent_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[ExceptionResponse]:
    q = (
        select(ComplianceException, ComplianceRule.rule_key, ComplianceRule.title, Agent.hostname)
        .outerjoin(ComplianceRule, ComplianceRule.id == ComplianceException.rule_id)
        .outerjoin(Agent, Agent.id == ComplianceException.agent_id)
        .order_by(ComplianceException.created_at.desc(), ComplianceException.id.desc())
    )
    if status:
        q = q.where(ComplianceException.status == status)
    if rule_id:
        q = q.where(ComplianceException.rule_id == rule_id)
    if agent_id:
        q = q.where(ComplianceException.agent_id == agent_id)

    items, next_cursor = await paginate_keyset(
        db, q,
        ts_col=ComplianceException.created_at, tie_col=ComplianceException.id,
        cursor=cursor, limit=limit,
    )

    count_q = select(func.count()).select_from(ComplianceException)
    if status:
        count_q = count_q.where(ComplianceException.status == status)
    if rule_id:
        count_q = count_q.where(ComplianceException.rule_id == rule_id)
    if agent_id:
        count_q = count_q.where(ComplianceException.agent_id == agent_id)
    total = (await db.execute(count_q)).scalar()

    return CursorPage[ExceptionResponse](
        items=[
            ExceptionResponse.model_validate(e).model_copy(
                update={"rule_key": rule_key, "rule_title": rule_title, "hostname": hostname}
            )
            for e, rule_key, rule_title, hostname in items
        ],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("/exceptions", response_model=ExceptionResponse, status_code=201)
async def create_exception(
    body: ExceptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.exceptions.create")),
) -> ExceptionResponse:
    exc = await ExceptionService(db).create(
        rule_id=body.rule_id,
        reason=body.reason,
        owner=body.owner,
        expires_at=body.expires_at,
        agent_id=body.agent_id,
        scope_selector=body.scope_selector,
        requested_by=safe_user_uuid(current_user),
        actor=current_user,
    )
    return ExceptionResponse.model_validate(exc)


@router.get("/exceptions/{exception_id}", response_model=ExceptionResponse)
async def get_exception(
    exception_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> ExceptionResponse:
    result = (
        await db.execute(
            select(ComplianceException, ComplianceRule.rule_key, ComplianceRule.title, Agent.hostname)
            .outerjoin(ComplianceRule, ComplianceRule.id == ComplianceException.rule_id)
            .outerjoin(Agent, Agent.id == ComplianceException.agent_id)
            .where(ComplianceException.id == exception_id)
        )
    ).first()
    if result is None:
        raise HTTPException(status_code=404, detail="Exception not found")
    row, rule_key, rule_title, hostname = result
    return ExceptionResponse.model_validate(row).model_copy(
        update={"rule_key": rule_key, "rule_title": rule_title, "hostname": hostname}
    )


@router.post("/exceptions/{exception_id}/approve", response_model=ExceptionResponse)
async def approve_exception(
    exception_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.exceptions.approve")),
) -> ExceptionResponse:
    row = (
        await db.execute(select(ComplianceException).where(ComplianceException.id == exception_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Exception not found")
    updated = await ExceptionService(db).approve(row, current_user, safe_user_uuid(current_user))
    return ExceptionResponse.model_validate(updated)


@router.post("/exceptions/{exception_id}/revoke", response_model=ExceptionResponse)
async def revoke_exception(
    exception_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.exceptions.revoke")),
) -> ExceptionResponse:
    row = (
        await db.execute(select(ComplianceException).where(ComplianceException.id == exception_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Exception not found")
    updated = await ExceptionService(db).revoke(row, current_user)
    return ExceptionResponse.model_validate(updated)
