"""
LokiLinux — EventProcessorWorker: validates, dedups, fingerprints, and
persists events published to lokilinux.events.raw.*.

The only writer to ClickHouse's `events` table (via EventRepository). Every
producer — the HTTP ingestion endpoint, the gRPC servicer, the heartbeat
monitor, the job executor — publishes raw EventIn-shaped JSON here instead
of touching ClickHouse directly; this worker is where dedup/fingerprinting/
persistence actually happens, once, in one place.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4
import asyncio
import json

import structlog

from lokilinux.ch import ClickHouseStore
from lokilinux.events.fingerprint import fingerprint
from lokilinux.events.repository import EVENT_INSERT_FLUSH_SEC, EventRepository
from lokilinux.events.schemas import EventIn, NormalizedEvent
from lokilinux.metrics import events_dropped_total, events_received_total
from lokilinux.nats_topics import EVENT_NORMALIZED, EVENT_RAW
from lokilinux.utils.flush_loop import flush_loop

logger = structlog.get_logger()

_DEDUP_TTL_SECONDS = 300


class EventProcessorWorker:
    def __init__(self, nats_client, cache, ch: ClickHouseStore) -> None:
        self.nats = nats_client
        self.cache = cache
        self.repository = EventRepository(ch)
        self._flush_task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.nats.subscribe(f"{EVENT_RAW}.*", cb=self._handle_raw)
        self._flush_task = asyncio.create_task(
            flush_loop(self.repository.flush, EVENT_INSERT_FLUSH_SEC, "event_processor")
        )
        logger.info("EventProcessorWorker started")

    async def stop(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
        await self.repository.flush()

    async def _handle_raw(self, msg) -> None:
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("event_processor.malformed_json", exc_info=True)
            events_dropped_total.labels(reason="malformed_json").inc()
            return
        if not isinstance(data, dict):
            logger.error("event_processor.malformed_json", reason="payload is not an object")
            events_dropped_total.labels(reason="malformed_json").inc()
            return

        event_id = data.get("event_id")
        tenant_id = data.get("tenant_id") or "default"
        try:
            event_uuid = UUID(str(event_id)) if event_id else uuid4()
        except ValueError:
            logger.warning("event_processor.invalid_event_id", event_id=str(event_id)[:64])
            events_dropped_total.labels(reason="invalid_event_id").inc()
            return

        try:
            validated = EventIn(**{k: v for k, v in data.items() if k not in ("event_id", "tenant_id")})
        except Exception:
            logger.warning("event_processor.validation_failed", raw=data, exc_info=True)
            events_dropped_total.labels(reason="invalid_schema").inc()
            return

        if event_id:
            dedup_key = f"ev:dedup:{event_id}"
            # False = another worker claimed it (redelivery, not an error). None = Redis is
            # down: keep the event, a rare duplicate beats losing every event in the outage.
            if await self.cache.set_nx_checked(dedup_key, ttl=_DEDUP_TTL_SECONDS) is False:
                return

        resolved_ts = validated.timestamp or datetime.now(timezone.utc)
        fp = fingerprint(tenant_id, validated.host_id, validated.type, validated.service)
        normalized = NormalizedEvent(
            **validated.model_dump(exclude={"timestamp"}),
            event_id=event_uuid,
            tenant_id=tenant_id,
            timestamp=resolved_ts,
            fingerprint=fp,
        )

        await self.repository.add(normalized)
        try:
            await self.nats.publish(EVENT_NORMALIZED, normalized.model_dump_json().encode())
        except Exception:
            # Stored, but signals/incidents never see it — make that visible.
            logger.error("event_processor.normalized_publish_failed", exc_info=True)
            events_dropped_total.labels(reason="normalized_publish_failed").inc()
        events_received_total.labels(source=normalized.source).inc()
