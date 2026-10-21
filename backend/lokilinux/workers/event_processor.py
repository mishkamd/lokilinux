"""
LokiLinux — EventProcessorWorker: validates, dedups, fingerprints, and
persists events published to lokilinux.events.raw.*.

The only writer to ClickHouse's `events` table (via EventRepository). Every
producer — the HTTP ingestion endpoint, the gRPC servicer, the heartbeat
monitor, the job executor — publishes raw EventIn-shaped JSON here instead
of touching ClickHouse directly; this worker is where dedup/fingerprinting/
persistence actually happens, once, in one place.

Delivery (MIS-139): the worker consumes from a DURABLE JetStream consumer on
the EVENTS stream instead of a plain core-NATS subscription. A core
subscription is fire-and-forget — whatever was published while the API was
down was gone for good. The stream already captured every published event
(24h retention), so a durable consumer turns that buffer into a delivery
guarantee: the consumer resumes from its last ack after a crash, and the
events published in between are replayed.

Ack discipline: a message is acked only AFTER the event it carried is durably
in ClickHouse. A failed flush leaves it unacked, so JetStream redelivers it
after ack_wait. Malformed/duplicate messages are acked immediately — they are
poison, redelivering them forever would stall the consumer.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4
import asyncio
import json

import structlog
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from lokilinux.ch import ClickHouseStore
from lokilinux.events.fingerprint import fingerprint
from lokilinux.events.repository import EVENT_INSERT_FLUSH_SEC, EventRepository
from lokilinux.events.schemas import EventIn, NormalizedEvent
from lokilinux.metrics import events_dropped_total, events_received_total
from lokilinux.nats_topics import EVENT_NORMALIZED, EVENT_RAW

logger = structlog.get_logger()

_DEDUP_TTL_SECONDS = 300

# Durable consumer name — stable across restarts, that's the point: a
# consumer that doesn't exist yet starts from NOW (no replay of the 24h
# backlog the live path already wrote to ClickHouse), an existing one
# resumes from its last ack.
_DURABLE = "event-processor"
_ACK_WAIT = 60  # seconds — nats-py wants a number, not a timedelta
_MAX_DELIVER = 5


class EventProcessorWorker:
    def __init__(self, nats_client, cache, ch: ClickHouseStore) -> None:
        self.nats = nats_client
        self.cache = cache
        self.repository = EventRepository(ch)
        # Messages whose event is buffered but not yet durably in ClickHouse.
        # Acked once the buffer drains (see _ack_drained).
        self._pending_acks: list = []
        self._subscription = None
        self._flush_task: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            await self._start_durable_consumer()
        except Exception:
            # Degraded, not dead: without JetStream we still process events,
            # we just lose the replay guarantee (MIS-139).
            logger.error("event_processor.durable_consumer_failed", exc_info=True)
            await self.nats.subscribe(f"{EVENT_RAW}.*", cb=self._handle_raw)
            logger.info("EventProcessorWorker started", mode="core-nats-fallback")
        else:
            logger.info("EventProcessorWorker started", mode="jetstream", durable=_DURABLE)
        # The buffer is only flushed on the next add() — without this loop an
        # idle stream would leave rows unacked (and unwritten) forever.
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def _start_durable_consumer(self) -> None:
        js = self.nats.jetstream()
        self._subscription = await js.subscribe(
            f"{EVENT_RAW}.*",
            durable=_DURABLE,
            stream="EVENTS",
            cb=self._handle_raw,
            config=ConsumerConfig(
                deliver_policy=DeliverPolicy.BY_START_TIME,
                opt_start_time=datetime.now(timezone.utc),
                ack_policy=AckPolicy.EXPLICIT,
                ack_wait=_ACK_WAIT,
                max_deliver=_MAX_DELIVER,
                filter_subject=f"{EVENT_RAW}.*",
            ),
        )

    async def stop(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            self._flush_task = None
        await self._flush_once()
        if self._subscription is not None:
            try:
                await self._subscription.unsubscribe()
            except Exception:
                logger.warning("event_processor.unsubscribe_failed", exc_info=True)

    async def _handle_raw(self, msg) -> None:
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("event_processor.malformed_json", exc_info=True)
            events_dropped_total.labels(reason="malformed_json").inc()
            await self._ack(msg)
            return

        event_id = data.get("event_id")
        tenant_id = data.get("tenant_id") or "default"

        try:
            validated = EventIn(**{k: v for k, v in data.items() if k not in ("event_id", "tenant_id")})
        except Exception:
            logger.warning("event_processor.validation_failed", raw=data, exc_info=True)
            events_dropped_total.labels(reason="invalid_schema").inc()
            await self._ack(msg)
            return

        if event_id:
            dedup_key = f"ev:dedup:{event_id}"
            if not await self.cache.set_nx(dedup_key, ttl=_DEDUP_TTL_SECONDS):
                await self._ack(msg)
                return  # another worker claimed it — redelivery, not an error

        resolved_ts = validated.timestamp or datetime.now(timezone.utc)
        fp = fingerprint(tenant_id, validated.host_id, validated.type, validated.service)
        normalized = NormalizedEvent(
            **validated.model_dump(exclude={"timestamp"}),
            event_id=UUID(event_id) if event_id else uuid4(),
            tenant_id=tenant_id,
            timestamp=resolved_ts,
            fingerprint=fp,
        )

        await self.repository.add(normalized)
        # Ack only once the row is durably in ClickHouse.
        self._pending_acks.append(msg)
        await self._ack_drained()
        try:
            await self.nats.publish(EVENT_NORMALIZED, normalized.model_dump_json().encode())
        except Exception:
            logger.error("event_processor.normalized_publish_failed", exc_info=True)
        events_received_total.labels(source=normalized.source).inc()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(EVENT_INSERT_FLUSH_SEC)
            try:
                await self._flush_once()
            except Exception:
                logger.error("event_processor.flush_loop_failed", exc_info=True)

    async def _flush_once(self) -> None:
        """Drain the buffer to ClickHouse, then ack whatever it contained."""
        await self.repository.flush()
        await self._ack_drained()

    async def _ack_drained(self) -> None:
        """Ack the pending messages once the repository buffer is empty —
        that means every buffered row made it to ClickHouse. If the flush
        failed the buffer isn't empty and nothing is acked, so JetStream
        redelivers."""
        if not self._pending_acks or self.repository.pending_count:
            return
        pending, self._pending_acks = self._pending_acks, []
        for msg in pending:
            await self._ack(msg)

    async def _ack(self, msg) -> None:
        try:
            await msg.ack()
        except Exception:
            logger.warning("event_processor.ack_failed", exc_info=True)
