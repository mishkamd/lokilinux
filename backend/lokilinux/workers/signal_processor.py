"""
LokiLinux — SignalProcessorWorker: EVENT_NORMALIZED + COMPLIANCE_DRIFT_DETECTED
-> detectors -> SignalService.

Subscribes both streams. Compliance drift payloads (their own shape, from
the lokilinux-compliance Go service — docs/compliance/04-PROTOCOL.md) get
wrapped into the minimal event-like object detectors actually read
(type/host_id/payload) before running through the same registry as
everything else — one detection path, not two.
"""

from types import SimpleNamespace
import json

import structlog

from lokilinux.ch import ClickHouseStore
from lokilinux.nats_topics import COMPLIANCE_DRIFT_DETECTED, EVENT_NORMALIZED
from lokilinux.signals.detectors import (
    DETECTORS,
    METRIC_SAMPLE_EVENT_TYPE,
    RECOVERY_EVENT_TYPE,
    RECOVERY_RESOLVES_SIGNAL_TYPE,
    detect_metric_samples,
)
from lokilinux.signals.repository import SignalOccurrenceRepository
from lokilinux.signals.service import SignalService

logger = structlog.get_logger()


class SignalProcessorWorker:
    def __init__(self, nats_client, db_session_factory, cache, ch: ClickHouseStore) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache
        self.occurrences = SignalOccurrenceRepository(ch)

    async def start(self) -> None:
        await self.nats.subscribe(EVENT_NORMALIZED, cb=self._handle_normalized_event)
        await self.nats.subscribe(COMPLIANCE_DRIFT_DETECTED, cb=self._handle_drift)
        logger.info("SignalProcessorWorker started")

    async def stop(self) -> None:
        await self.occurrences.flush()

    async def _handle_normalized_event(self, msg) -> None:
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("signal_processor.malformed_json", exc_info=True)
            return
        event = SimpleNamespace(
            type=data.get("type"), host_id=data.get("host_id"), payload=data.get("payload") or {},
        )
        await self._process(event, tenant_id=data.get("tenant_id") or "default")

    async def _handle_drift(self, msg) -> None:
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("signal_processor.malformed_drift_json", exc_info=True)
            return
        event = SimpleNamespace(
            type="compliance.drift.detected",
            host_id=data.get("agent_id") or data.get("host_id"),
            payload=data,
        )
        await self._process(event, tenant_id="default")

    async def _process(self, event, *, tenant_id: str) -> None:
        try:
            async with self.db_factory() as db:
                svc = SignalService(db, self.nats, self.occurrences)

                if event.type == RECOVERY_EVENT_TYPE:
                    await svc.resolve_by_fingerprint(tenant_id, event.host_id, RECOVERY_RESOLVES_SIGNAL_TYPE)
                    return

                if event.type == METRIC_SAMPLE_EVENT_TYPE:
                    for detected in await detect_metric_samples(event, self.cache):
                        await svc.upsert_signal(detected, tenant_id=tenant_id)
                    return

                detector = DETECTORS.get(event.type)
                if detector is None:
                    return
                detected = detector(event)
                if detected is not None:
                    await svc.upsert_signal(detected, tenant_id=tenant_id)
        except Exception:
            logger.error("signal_processor.process_failed", event_type=getattr(event, "type", None), exc_info=True)
