"""
LokiLinux — shared event-emission helper for in-process producers (gRPC
servicer, workers). The HTTP ingestion endpoint (routers/events.py) does NOT
use this — it already builds and publishes its own validated EventIn shape.

emit() swallows and logs NATS failures: publishing an event must never break
the host flow (heartbeat processing, job completion, ...) — same policy as
the existing alert-publish try/except blocks elsewhere in this codebase.

is_pipeline_enabled() checks the "observability.event_pipeline_enabled" kill
switch (settings_schema.py), Redis-cached for 30s using the same
fail-open-on-lookup-error pattern as middleware/rate_limit.py's
_rate_limit_config — an unreachable settings store should not go silent
across the whole app, just accept a stale flag for up to 30s.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import json

import structlog

from lokilinux.nats_topics import EVENT_RAW
from lokilinux.settings_schema import get_setting_value

logger = structlog.get_logger()

_TENANT_ID = "default"
_PIPELINE_ENABLED_CACHE_KEY = "settings:observability:event_pipeline_enabled"
_PIPELINE_ENABLED_CACHE_TTL = 30


async def emit(
    nats: Any,
    source: str,
    type_: str,
    *,
    host_id: str | None = None,
    service: str | None = None,
    severity: str = "INFO",
    payload: dict[str, Any] | None = None,
    event_id: str | None = None,
) -> None:
    event = {
        "schema_version": 1,
        "event_id": event_id or str(uuid4()),
        "tenant_id": _TENANT_ID,
        "source": source,
        "type": type_,
        "severity": severity,
        "host_id": host_id,
        "service": service,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }
    try:
        await nats.publish(f"{EVENT_RAW}.{source}", json.dumps(event).encode())
    except Exception:
        logger.error("events.emit_failed", source=source, type=type_, exc_info=True)


async def is_pipeline_enabled(cache: Any, db: Any) -> bool:
    cached = await cache.get_cached(_PIPELINE_ENABLED_CACHE_KEY)
    if cached is not None:
        return bool(cached)
    try:
        enabled = await get_setting_value(db, "observability.event_pipeline_enabled")
    except Exception:
        logger.warning("events.pipeline_flag_unavailable_fail_open", exc_info=True)
        return True
    await cache.set_cached(_PIPELINE_ENABLED_CACHE_KEY, enabled, ttl=_PIPELINE_ENABLED_CACHE_TTL)
    return bool(enabled)
