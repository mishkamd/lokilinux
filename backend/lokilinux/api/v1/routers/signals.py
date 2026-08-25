"""
LokiLinux — Signals router: list + resolve/suppress.
"""

from datetime import datetime
from typing import Any
from uuid import UUID
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.dependencies import get_db, get_nats
from lokilinux.nats_topics import SIGNAL_RESOLVED
from lokilinux.schemas.common import decode_cursor, encode_cursor
from lokilinux.signals.models import Signal
from lokilinux.signals.schemas import SignalListResponse, SignalResponse

logger = structlog.get_logger()

router = APIRouter()

_TENANT_ID = "default"


@router.get("", response_model=SignalListResponse)
async def list_signals(
    status: str | None = None,
    severity: str | None = None,
    type: str | None = None,
    host_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(get_current_user),
) -> SignalListResponse:
    q = (
        select(Signal)
        .where(Signal.tenant_id == _TENANT_ID)
        .order_by(Signal.last_seen.desc(), Signal.id.desc())
    )
    if status:
        q = q.where(Signal.status == status)
    if severity:
        q = q.where(Signal.severity == severity)
    if type:
        q = q.where(Signal.type == type)
    if host_id:
        q = q.where(Signal.host_id == host_id)
    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        ts = datetime.fromisoformat(ts_str)
        q = q.where((Signal.last_seen < ts) | ((Signal.last_seen == ts) & (Signal.id < UUID(uid))))

    rows = (await db.execute(q.limit(limit + 1))).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.last_seen.isoformat()}:{last.id}")
    return SignalListResponse(
        items=[SignalResponse.model_validate(s) for s in items], next_cursor=next_cursor
    )


async def _get_or_404(db: AsyncSession, signal_id: UUID) -> Signal:
    signal = await db.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@router.post("/{signal_id}/resolve", response_model=SignalResponse)
async def resolve_signal(
    signal_id: UUID,
    db: AsyncSession = Depends(get_db),
    nats: Any = Depends(get_nats),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> Signal:
    signal = await _get_or_404(db, signal_id)
    signal.status = "RESOLVED"
    await db.flush()
    try:
        await nats.publish(
            SIGNAL_RESOLVED,
            json.dumps({"fingerprint": signal.fingerprint, "signal_id": str(signal.id)}).encode(),
        )
    except Exception:
        logger.error("signal.resolve_publish_failed", signal_id=str(signal.id), exc_info=True)
    return signal


@router.post("/{signal_id}/suppress", response_model=SignalResponse)
async def suppress_signal(
    signal_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> Signal:
    signal = await _get_or_404(db, signal_id)
    signal.status = "SUPPRESSED"
    await db.flush()
    return signal
