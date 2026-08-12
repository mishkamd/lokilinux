"""
LokiLinux — Compliance: Drift Detection router.

Read-only + acknowledge. drift_events rows are written by
lokilinux-compliance (services/compliance/internal/ingest — detectDrift),
never by this API — mirrors how inventory.py only ever reads what the Go
service wrote.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.models.drift import DriftDetail, DriftEvent
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.drift import DriftDetailResponse, DriftEventResponse
from lokilinux.services.audit_service import AuditService

router = APIRouter()


@router.get("/drift-events", response_model=CursorPage[DriftEventResponse])
async def list_drift_events(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    severity: str | None = Query(None),
    domain: str | None = Query(None),
    agent_id: UUID | None = Query(None),
    acknowledged: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[DriftEventResponse]:
    q = select(DriftEvent).order_by(DriftEvent.time.desc(), DriftEvent.id.desc())
    if severity:
        q = q.where(DriftEvent.severity == severity)
    if domain:
        q = q.where(DriftEvent.domain == domain)
    if agent_id:
        q = q.where(DriftEvent.agent_id == agent_id)
    if acknowledged is not None:
        q = q.where(
            DriftEvent.acknowledged_at.isnot(None)
            if acknowledged
            else DriftEvent.acknowledged_at.is_(None)
        )
    if cursor:
        raw = decode_cursor(cursor)
        ts_str, eid = raw.rsplit(":", 1)
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (DriftEvent.time < ts) | ((DriftEvent.time == ts) & (DriftEvent.id < UUID(eid)))
        )
    q = q.limit(limit + 1)

    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.time.isoformat()}:{last.id}")

    # total count (no cursor filter — lightweight approximate, mirrors servers.py)
    count_q = select(func.count()).select_from(DriftEvent)
    if severity:
        count_q = count_q.where(DriftEvent.severity == severity)
    if domain:
        count_q = count_q.where(DriftEvent.domain == domain)
    if agent_id:
        count_q = count_q.where(DriftEvent.agent_id == agent_id)
    if acknowledged is not None:
        count_q = count_q.where(
            DriftEvent.acknowledged_at.isnot(None)
            if acknowledged
            else DriftEvent.acknowledged_at.is_(None)
        )
    total = (await db.execute(count_q)).scalar()

    return CursorPage[DriftEventResponse](
        items=[DriftEventResponse.model_validate(e) for e in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/drift-events/{event_id}", response_model=DriftEventResponse)
async def get_drift_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> DriftEventResponse:
    # id alone (not the full time/agent_id/id hypertable PK) is enough —
    # it's server-generated via gen_random_uuid() so collisions aren't a
    # practical concern, and the frontend only ever has the bare id to link with.
    row = (
        await db.execute(select(DriftEvent).where(DriftEvent.id == event_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Drift event not found")
    return DriftEventResponse.model_validate(row)


@router.get("/drift-events/{event_id}/details", response_model=list[DriftDetailResponse])
async def list_drift_details(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[DriftDetailResponse]:
    rows = (
        (await db.execute(select(DriftDetail).where(DriftDetail.drift_event_id == event_id)))
        .scalars()
        .all()
    )
    return [DriftDetailResponse.model_validate(d) for d in rows]


@router.post("/drift-events/{event_id}/acknowledge", response_model=DriftEventResponse)
async def acknowledge_drift_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> DriftEventResponse:
    row = (
        await db.execute(select(DriftEvent).where(DriftEvent.id == event_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Drift event not found")

    row.acknowledged_by = safe_user_uuid(current_user)
    row.acknowledged_at = datetime.utcnow()
    await db.commit()

    await AuditService(db).log(
        action="compliance.drift_event_acknowledged",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="drift_event",
        resource_id=str(event_id),
        changes={"domain": row.domain, "agent_id": str(row.agent_id)},
    )
    return DriftEventResponse.model_validate(row)
