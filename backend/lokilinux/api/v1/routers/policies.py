"""
LokiLinux — Policies router.

CRUD for policies + POST /{id}/run (creates a real Job — replaces the old
/apply, which only published a NATS event that got counted and forgotten,
never executing anything). Version is auto-incremented on PATCH.
"""

import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.cache import RedisCache
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.models.policy import Policy, PolicyAudit
from lokilinux.nats_topics import POLICY_CHANGED
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.policy import (
    PolicyAuditResponse,
    PolicyCreate,
    PolicyResponse,
    PolicyRunResponse,
    PolicyUpdate,
    TriggerType,
)
from lokilinux.services.policy_service import compute_next_run_at, run_policy

router = APIRouter()


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=CursorPage[PolicyResponse])
async def list_policies(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    policy_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[PolicyResponse]:
    q = select(Policy).order_by(Policy.priority.asc(), Policy.created_at.desc())

    if policy_type:
        q = q.where(Policy.policy_type == policy_type)

    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (Policy.created_at < ts)
            | ((Policy.created_at == ts) & (Policy.id < UUID(uid)))
        )

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")

    return CursorPage[PolicyResponse](
        items=[PolicyResponse.model_validate(p) for p in items],
        next_cursor=next_cursor,
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_model=PolicyResponse, status_code=201)
async def create_policy(
    body: PolicyCreate,
    db: AsyncSession = Depends(get_db),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PolicyResponse:
    next_run_at = None
    cron_expr = body.cron_expr
    if body.trigger_type == TriggerType.SCHEDULE and cron_expr:
        try:
            next_run_at = compute_next_run_at(cron_expr)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"invalid cron_expr: {exc}") from exc

    policy = Policy(
        name=body.name,
        description=body.description,
        policy_type=body.policy_type.value if body.policy_type else None,
        rules=body.rules,
        target_servers=body.target_servers,
        is_enabled=body.is_enabled,
        priority=body.priority,
        version=1,
        created_by=safe_user_uuid(current_user),
        trigger_type=body.trigger_type.value,
        cron_expr=body.cron_expr,
        next_run_at=next_run_at,
        actions=[a.model_dump() for a in body.actions],
        execution=body.execution.model_dump(),
        severity=body.severity,
        tags=body.tags,
    )
    db.add(policy)
    await db.flush()

    db.add(PolicyAudit(
        policy_id=policy.id,
        changed_by=safe_user_uuid(current_user),
        change_type="CREATE",
        new_value=json.loads(PolicyResponse.model_validate(policy).model_dump_json()),
    ))
    await db.commit()

    await nats.publish(
        POLICY_CHANGED,
        json.dumps({"policy_id": str(policy.id), "action": "created"}).encode(),
    )
    return PolicyResponse.model_validate(policy)


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> PolicyResponse:
    row = (await db.execute(select(Policy).where(Policy.id == policy_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return PolicyResponse.model_validate(row)


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: UUID,
    body: PolicyUpdate,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PolicyResponse:
    row = (await db.execute(select(Policy).where(Policy.id == policy_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    old_value = json.loads(PolicyResponse.model_validate(row).model_dump_json())

    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field == "actions" and value is not None:
            value = [a if isinstance(a, dict) else a.model_dump() for a in value]
        elif field == "execution" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
        setattr(row, field, value)
    row.version = (row.version or 1) + 1  # auto-increment version

    new_trigger = row.trigger_type
    new_cron = row.cron_expr
    if "trigger_type" in changes or "cron_expr" in changes:
        if new_trigger == TriggerType.SCHEDULE.value:
            if not new_cron:
                raise HTTPException(status_code=422, detail="cron_expr is required when trigger_type is SCHEDULE")
            try:
                row.next_run_at = compute_next_run_at(new_cron)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"invalid cron_expr: {exc}") from exc
        else:
            row.next_run_at = None

    db.add(PolicyAudit(
        policy_id=policy_id,
        changed_by=safe_user_uuid(current_user),
        change_type="UPDATE",
        old_value=old_value,
        new_value=json.loads(PolicyResponse.model_validate(row).model_dump_json()),
    ))

    await db.commit()
    await cache.invalidate(f"policy:{policy_id}:detail")
    await nats.publish(
        POLICY_CHANGED,
        json.dumps({"policy_id": str(policy_id), "action": "updated"}).encode(),
    )
    return PolicyResponse.model_validate(row)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: UUID,
    db: AsyncSession = Depends(get_db),
    nats=Depends(get_nats),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    row = (await db.execute(select(Policy).where(Policy.id == policy_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    # No PolicyAudit row for DELETE — policy_audit.policy_id is
    # ON DELETE CASCADE (models/policy.py), so any audit row written here
    # (including this policy's own CREATE/UPDATE history) would vanish the
    # instant the policy row does. Deletion is still visible via
    # POLICY_CHANGED below and the ordinary application log.
    await db.delete(row)
    await db.commit()
    await nats.publish(
        POLICY_CHANGED,
        json.dumps({"policy_id": str(policy_id), "action": "deleted"}).encode(),
    )


# ── Run now ───────────────────────────────────────────────────────────────────

@router.post("/{policy_id}/run", response_model=PolicyRunResponse)
async def run_policy_now(
    policy_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PolicyRunResponse:
    row = (await db.execute(select(Policy).where(Policy.id == policy_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    job_ids, matched = await run_policy(db, row, cache, triggered_by="manual")
    return PolicyRunResponse(job_ids=job_ids, matched_agents=matched)


# ── Audit trail ───────────────────────────────────────────────────────────────

@router.get("/{policy_id}/audit", response_model=list[PolicyAuditResponse])
async def get_policy_audit(
    policy_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[PolicyAuditResponse]:
    rows = (
        await db.execute(
            select(PolicyAudit)
            .where(PolicyAudit.policy_id == policy_id)
            # id as tiebreaker: Postgres's now() is the transaction start
            # time, constant for every statement in the same transaction —
            # two audits from rapid-fire requests inside one test transaction
            # (or any single real transaction) can land on the identical
            # changed_at, which would make ordering by changed_at alone
            # non-deterministic. Confirmed by a real test failure.
            .order_by(PolicyAudit.changed_at.desc(), PolicyAudit.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [PolicyAuditResponse.model_validate(r) for r in rows]
