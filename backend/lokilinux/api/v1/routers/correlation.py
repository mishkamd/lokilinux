"""
LokiLinux — Correlation rules router: CRUD.

Validation (conditions shape, window_seconds range, positive weights/
threshold) lives in the request schema (signals/schemas.py::
CorrelationRuleCreate) — signal names are freeform, not restricted to the
detectors registry, so a rule can reference a signal type that doesn't
exist yet (e.g. one a not-yet-written detector will start emitting).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.dependencies import get_db
from lokilinux.signals.models import CorrelationRule
from lokilinux.signals.schemas import CorrelationRuleCreate, CorrelationRuleResponse

router = APIRouter()

_TENANT_ID = "default"


@router.get("/rules", response_model=list[CorrelationRuleResponse])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(get_current_user),
) -> list[CorrelationRule]:
    rows = (
        await db.execute(select(CorrelationRule).where(CorrelationRule.tenant_id == _TENANT_ID))
    ).scalars().all()
    return list(rows)


@router.post("/rules", response_model=CorrelationRuleResponse, status_code=201)
async def create_rule(
    payload: CorrelationRuleCreate,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> CorrelationRule:
    rule = CorrelationRule(tenant_id=_TENANT_ID, **payload.model_dump())
    db.add(rule)
    await db.flush()
    return rule


@router.patch("/rules/{rule_id}", response_model=CorrelationRuleResponse)
async def update_rule(
    rule_id: UUID,
    payload: CorrelationRuleCreate,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> CorrelationRule:
    rule = await db.get(CorrelationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Correlation rule not found")
    for field, value in payload.model_dump().items():
        setattr(rule, field, value)
    rule.version += 1
    await db.flush()
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    rule = await db.get(CorrelationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Correlation rule not found")
    await db.delete(rule)
    await db.flush()
