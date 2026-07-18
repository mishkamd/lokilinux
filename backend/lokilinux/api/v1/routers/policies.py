"""
LokiLinux — Policies router.

CRUD for policies + POST /{id}/apply.
Version is auto-incremented on PATCH.
"""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, safe_user_uuid
from lokilinux.cache import RedisCache
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.models.policy import Policy
from lokilinux.nats_topics import POLICY_APPLY, POLICY_CHANGED
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.policy import PolicyCreate, PolicyResponse, PolicyUpdate

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
        from datetime import datetime
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
    current_user: dict = Depends(get_current_user),
) -> PolicyResponse:
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
    )
    db.add(policy)
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
    _: dict = Depends(get_current_user),
) -> PolicyResponse:
    row = (await db.execute(select(Policy).where(Policy.id == policy_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.version = (row.version or 1) + 1  # auto-increment version

    await db.commit()
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
    _: dict = Depends(get_current_user),
) -> None:
    row = (await db.execute(select(Policy).where(Policy.id == policy_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    await db.delete(row)
    await db.commit()
    await nats.publish(
        POLICY_CHANGED,
        json.dumps({"policy_id": str(policy_id), "action": "deleted"}).encode(),
    )


# ── Apply ─────────────────────────────────────────────────────────────────────

@router.post("/{policy_id}/apply")
async def apply_policy(
    policy_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    nats=Depends(get_nats),
    _: dict = Depends(get_current_user),
) -> dict:
    row = (await db.execute(select(Policy).where(Policy.id == policy_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    await nats.publish(
        POLICY_APPLY,
        json.dumps({"policy_id": str(policy_id), "scope": body}).encode(),
    )
    return {"policy_id": str(policy_id), "status": "applying"}
