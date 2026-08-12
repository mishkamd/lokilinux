"""
LokiLinux — Compliance: Inventory Collector router (read-only).

Snapshot ingest itself is write-side (agent -> gRPC passthrough -> NATS ->
lokilinux-compliance, docs/compliance/04-PROTOCOL.md) — not exposed here.
This router only reads what's already been ingested: latest per-domain
snapshot and its delta history. Both endpoints return 404/empty naturally
(never fabricated data) since nothing populates inventory_snapshots/
inventory_deltas until the Go ingest service (docs/compliance/02-GO-SERVICE.md)
is built — that's an honest gap, not a bug in this router.
"""

import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.models.inventory import InventoryBlob, InventoryDelta, InventorySnapshot
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.inventory import InventoryDeltaResponse, InventorySnapshotResponse

router = APIRouter()


def _decode_facts(body: bytes | None) -> dict | None:
    """inventory_blobs.body is stored as JSON bytes (docs/compliance/01-DATA-MODEL.md
    describes an eventual zstd-compressed body once the Go ingest pipeline
    exists; nothing writes compressed bodies yet, so this reads plain JSON
    and degrades to None on anything it can't decode rather than raising —
    a malformed or future-compressed blob should not break the read endpoint).
    """
    if body is None:
        return None
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


@router.get("/agents/{agent_id}/inventory/{domain}", response_model=InventorySnapshotResponse)
async def get_latest_inventory_snapshot(
    agent_id: UUID,
    domain: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> InventorySnapshotResponse:
    row = (
        await db.execute(
            select(InventorySnapshot)
            .where(InventorySnapshot.agent_id == agent_id, InventorySnapshot.domain == domain)
            .order_by(InventorySnapshot.taken_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No inventory snapshot found for this agent/domain")

    blob = (
        await db.execute(select(InventoryBlob).where(InventoryBlob.content_hash == row.content_hash))
    ).scalar_one_or_none()

    return InventorySnapshotResponse(
        id=row.id,
        agent_id=row.agent_id,
        domain=row.domain,
        content_hash=row.content_hash,
        taken_at=row.taken_at,
        facts=_decode_facts(blob.body if blob else None),
    )


@router.get("/agents/{agent_id}/inventory/{domain}/history", response_model=CursorPage[InventoryDeltaResponse])
async def get_inventory_delta_history(
    agent_id: UUID,
    domain: str,
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[InventoryDeltaResponse]:
    q = (
        select(InventoryDelta)
        .where(InventoryDelta.agent_id == agent_id, InventoryDelta.domain == domain)
        .order_by(InventoryDelta.time.desc())
    )
    if cursor:
        ts = datetime.fromisoformat(decode_cursor(cursor))
        q = q.where(InventoryDelta.time < ts)

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor: str | None = None
    if has_more and items:
        next_cursor = encode_cursor(items[-1].time.isoformat())

    # total count (no cursor filter — lightweight approximate, mirrors servers.py)
    count_q = select(func.count()).select_from(InventoryDelta).where(
        InventoryDelta.agent_id == agent_id, InventoryDelta.domain == domain
    )
    total = (await db.execute(count_q)).scalar()

    return CursorPage[InventoryDeltaResponse](
        items=[InventoryDeltaResponse.model_validate(d) for d in items],
        next_cursor=next_cursor,
        total=total,
    )
