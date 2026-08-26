"""
LokiLinux — Event ingestion + query.

POST validates each event (EventIn), stamps tenant_id, and publishes to
EVENT_RAW.{source} — EventProcessorWorker (Task A5) owns dedup, fingerprinting,
and the actual ClickHouse write. This endpoint never touches ClickHouse itself.

GET reads back through EventRepository.query() against ClickHouse — a
separate, ordinary JWT-authenticated read path like every other list
endpoint in this API.
"""

from datetime import datetime
from typing import Any
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
import structlog

from lokilinux.auth.dependencies import get_current_user
from lokilinux.ch import ClickHouseStore
from lokilinux.config import get_settings
from lokilinux.dependencies import get_cache, get_ch, get_nats
from lokilinux.events.repository import EventRepository
from lokilinux.events.schemas import EventIn
from lokilinux.nats_topics import EVENT_RAW
from lokilinux.schemas.common import decode_cursor, encode_cursor

logger = structlog.get_logger()

router = APIRouter()

_MAX_BATCH = 100
# Single-tenant today (plan decision 2) — every row still carries tenant_id so
# multi-tenancy is additive later, not a retrofit.
_TENANT_ID = "default"


@router.post("")
async def ingest_events(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
    cache: Any = Depends(get_cache),
    nats: Any = Depends(get_nats),
) -> dict[str, Any]:
    body = await request.json()
    if isinstance(body, dict) and "events" in body:
        raw_events = body["events"]
    else:
        raw_events = [body]
    if not isinstance(raw_events, list) or not raw_events:
        raise HTTPException(status_code=422, detail="expected an event or {\"events\": [...]}")
    if len(raw_events) > _MAX_BATCH:
        raise HTTPException(status_code=422, detail=f"max {_MAX_BATCH} events per batch")

    principal = current_user.get("id") or "unknown"
    settings = get_settings()
    window = int(datetime.now().timestamp() // 60)
    count = await cache.incr(f"rate:ev:{principal}:{window}", ttl=90)
    if count > settings.event_rate_per_agent_per_min:
        raise HTTPException(status_code=429, detail="event rate limit exceeded")

    accepted = 0
    rejected: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            rejected.append({"index": idx, "reason": "event must be an object"})
            continue
        try:
            event = EventIn(**raw)
        except Exception as exc:
            rejected.append({"index": idx, "reason": str(exc)})
            continue
        payload = {**event.model_dump(mode="json"), "tenant_id": _TENANT_ID}
        await nats.publish(f"{EVENT_RAW}.{event.source}", json.dumps(payload).encode())
        accepted += 1

    return {"accepted": accepted, "rejected": rejected}


@router.get("")
async def list_events(
    type: str | None = None,
    source: str | None = None,
    host_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    _: dict[str, Any] = Depends(get_current_user),
    ch: ClickHouseStore = Depends(get_ch),
) -> dict[str, Any]:
    before: tuple[datetime, str] | None = None
    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, event_id = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        before = (datetime.fromisoformat(ts_str), event_id)

    repo = EventRepository(ch)
    result = await repo.query(
        _TENANT_ID, type=type, source=source, host_id=host_id, limit=limit, before=before
    )
    next_cursor = None
    if result["next_before"]:
        ts, event_id = result["next_before"]
        next_cursor = encode_cursor(f"{ts.isoformat()}:{event_id}")
    return {"items": result["items"], "next_cursor": next_cursor}
