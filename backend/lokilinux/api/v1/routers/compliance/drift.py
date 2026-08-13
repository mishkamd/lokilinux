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
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.models.agent import Agent
from lokilinux.models.drift import DriftDetail, DriftEvent
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.drift import DriftDetailResponse, DriftEventResponse
from lokilinux.services.audit_service import AuditService

router = APIRouter()

# OPEN -> ACKNOWLEDGED is the only forward transition acknowledge itself
# performs; suppress/resolve close the incident outright from any
# still-open state. A CLOSED incident (RESOLVED/SUPPRESSED/EXCEPTION) never
# transitions back — a reappearing deviation opens a fresh drift_events row
# instead (services/compliance/internal/ingest's correlationKey dedup only
# matches OPEN/ACKNOWLEDGED, docs/compliance §9).
_OPEN_STATUSES = ("OPEN", "ACKNOWLEDGED", "IN_REMEDIATION")


class SuppressDriftRequest(BaseModel):
    reason: str | None = None


@router.get("/drift-events", response_model=CursorPage[DriftEventResponse])
async def list_drift_events(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    severity: str | None = Query(None),
    domain: str | None = Query(None),
    agent_id: UUID | None = Query(None),
    acknowledged: bool | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[DriftEventResponse]:
    q = (
        select(DriftEvent, Agent.hostname)
        .outerjoin(Agent, Agent.id == DriftEvent.agent_id)
        .order_by(DriftEvent.time.desc(), DriftEvent.id.desc())
    )
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
    if status:
        q = q.where(DriftEvent.status == status)
    if cursor:
        raw = decode_cursor(cursor)
        ts_str, eid = raw.rsplit(":", 1)
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (DriftEvent.time < ts) | ((DriftEvent.time == ts) & (DriftEvent.id < UUID(eid)))
        )
    q = q.limit(limit + 1)

    rows = (await db.execute(q)).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1][0]
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
    if status:
        count_q = count_q.where(DriftEvent.status == status)
    total = (await db.execute(count_q)).scalar()

    return CursorPage[DriftEventResponse](
        items=[
            DriftEventResponse.model_validate(e).model_copy(update={"hostname": hostname})
            for e, hostname in items
        ],
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
    result = (
        await db.execute(
            select(DriftEvent, Agent.hostname)
            .outerjoin(Agent, Agent.id == DriftEvent.agent_id)
            .where(DriftEvent.id == event_id)
        )
    ).first()
    if result is None:
        raise HTTPException(status_code=404, detail="Drift event not found")
    row, hostname = result
    return DriftEventResponse.model_validate(row).model_copy(update={"hostname": hostname})


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

    if row.status not in _OPEN_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot acknowledge from status {row.status}")

    row.acknowledged_by = safe_user_uuid(current_user)
    row.acknowledged_at = datetime.utcnow()
    row.status = "ACKNOWLEDGED"
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


@router.post("/drift-events/{event_id}/suppress", response_model=DriftEventResponse)
async def suppress_drift_event(
    event_id: UUID,
    body: SuppressDriftRequest = SuppressDriftRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> DriftEventResponse:
    """Marks a drift incident as intentionally ignored (noisy/expected,
    distinct from an exception on the underlying rule — docs/compliance §9).
    Correlation dedup only matches OPEN/ACKNOWLEDGED, so if the same
    deviation reappears it opens a fresh incident rather than silently
    reopening this one."""
    row = (
        await db.execute(select(DriftEvent).where(DriftEvent.id == event_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Drift event not found")
    if row.status not in _OPEN_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot suppress from status {row.status}")

    actor_id = safe_user_uuid(current_user)
    row.status = "SUPPRESSED"
    row.suppressed_by = actor_id
    await db.commit()

    await AuditService(db).log(
        action="compliance.drift_event_suppressed",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="drift_event",
        resource_id=str(event_id),
        changes={"domain": row.domain, "agent_id": str(row.agent_id), "reason": body.reason},
    )
    return DriftEventResponse.model_validate(row)


@router.post("/drift-events/{event_id}/resolve", response_model=DriftEventResponse)
async def resolve_drift_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> DriftEventResponse:
    """Manually closes a drift incident as fixed. Remediation verification
    (docs/compliance §14) also transitions drift to RESOLVED on its own path
    once that's wired up — this endpoint is the manual "I fixed it outside
    the tool" close."""
    row = (
        await db.execute(select(DriftEvent).where(DriftEvent.id == event_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Drift event not found")
    if row.status not in _OPEN_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot resolve from status {row.status}")

    row.status = "RESOLVED"
    row.resolved_at = datetime.utcnow()
    await db.commit()

    await AuditService(db).log(
        action="compliance.drift_event_resolved",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="drift_event",
        resource_id=str(event_id),
        changes={"domain": row.domain, "agent_id": str(row.agent_id)},
    )
    return DriftEventResponse.model_validate(row)
