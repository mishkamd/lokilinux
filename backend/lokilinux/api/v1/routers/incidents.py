"""
LokiLinux — Incidents router: list/detail/timeline/evidence + ack/resolve/reopen.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.ch import ClickHouseStore
from lokilinux.dependencies import get_cache, get_ch, get_db, get_nats
from lokilinux.incidents.evidence import query_evidence
from lokilinux.incidents.lifecycle import IllegalTransition
from lokilinux.incidents.models import Incident, IncidentSignal, IncidentTimeline
from lokilinux.incidents.schemas import (
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentResponse,
    IncidentTimelineEntry,
)
from lokilinux.incidents.service import IncidentService
from lokilinux.schemas.common import decode_cursor, encode_cursor
from lokilinux.signals.models import Signal
from lokilinux.signals.schemas import SignalResponse

router = APIRouter()

_TENANT_ID = "default"
_TIMELINE_LIMIT = 20


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    status: str | None = None,
    severity: str | None = None,
    type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(get_current_user),
) -> IncidentListResponse:
    q = (
        select(Incident)
        .where(Incident.tenant_id == _TENANT_ID)
        .order_by(Incident.started_at.desc(), Incident.id.desc())
    )
    if status:
        q = q.where(Incident.status == status)
    if severity:
        q = q.where(Incident.severity == severity)
    if type:
        q = q.where(Incident.type == type)
    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        ts = datetime.fromisoformat(ts_str)
        q = q.where((Incident.started_at < ts) | ((Incident.started_at == ts) & (Incident.id < UUID(uid))))

    rows = (await db.execute(q.limit(limit + 1))).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.started_at.isoformat()}:{last.id}")
    return IncidentListResponse(
        items=[IncidentResponse.model_validate(i) for i in items], next_cursor=next_cursor
    )


async def _get_or_404(db: AsyncSession, incident_id: UUID) -> Incident:
    incident = await db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(get_current_user),
) -> IncidentDetailResponse:
    incident = await _get_or_404(db, incident_id)

    signal_ids = (
        await db.execute(select(IncidentSignal.signal_id).where(IncidentSignal.incident_id == incident_id))
    ).scalars().all()
    signals = (
        (await db.execute(select(Signal).where(Signal.id.in_(signal_ids)))).scalars().all()
        if signal_ids else []
    )
    timeline = (
        await db.execute(
            select(IncidentTimeline)
            .where(IncidentTimeline.incident_id == incident_id)
            .order_by(IncidentTimeline.ts.desc())
            .limit(_TIMELINE_LIMIT)
        )
    ).scalars().all()

    return IncidentDetailResponse(
        **IncidentResponse.model_validate(incident).model_dump(),
        signals=[SignalResponse.model_validate(s) for s in signals],
        timeline=[IncidentTimelineEntry.model_validate(t) for t in timeline],
    )


@router.get("/{incident_id}/timeline", response_model=list[IncidentTimelineEntry])
async def get_timeline(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(get_current_user),
) -> list[IncidentTimeline]:
    await _get_or_404(db, incident_id)
    rows = (
        await db.execute(
            select(IncidentTimeline)
            .where(IncidentTimeline.incident_id == incident_id)
            .order_by(IncidentTimeline.ts.asc())
        )
    ).scalars().all()
    return list(rows)


@router.get("/{incident_id}/evidence")
async def get_evidence(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    ch: ClickHouseStore = Depends(get_ch),
    _: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    await _get_or_404(db, incident_id)
    rows = await query_evidence(ch, _TENANT_ID, str(incident_id))
    return {"items": rows}


async def _transition_or_error(
    db: AsyncSession, nats: Any, cache: Any, ch: Any, incident_id: UUID, actor, method: str
) -> Incident:
    svc = IncidentService(db, nats, cache, ch)
    try:
        return await getattr(svc, method)(incident_id, actor)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{incident_id}/ack", response_model=IncidentResponse)
async def ack_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: Any = Depends(get_cache),
    nats: Any = Depends(get_nats),
    ch: ClickHouseStore = Depends(get_ch),
    current_user: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> Incident:
    return await _transition_or_error(db, nats, cache, ch, incident_id, safe_user_uuid(current_user), "ack")


@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
async def resolve_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: Any = Depends(get_cache),
    nats: Any = Depends(get_nats),
    ch: ClickHouseStore = Depends(get_ch),
    current_user: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> Incident:
    return await _transition_or_error(db, nats, cache, ch, incident_id, safe_user_uuid(current_user), "resolve")


@router.post("/{incident_id}/reopen", response_model=IncidentResponse)
async def reopen_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: Any = Depends(get_cache),
    nats: Any = Depends(get_nats),
    ch: ClickHouseStore = Depends(get_ch),
    current_user: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> Incident:
    return await _transition_or_error(db, nats, cache, ch, incident_id, safe_user_uuid(current_user), "reopen")
