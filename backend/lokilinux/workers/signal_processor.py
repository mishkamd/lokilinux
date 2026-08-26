"""
LokiLinux — SignalProcessorWorker: EVENT_NORMALIZED -> detectors -> SignalService.

Subscribes the normalized-event stream and runs each event through the same
detector registry as everything else.
"""

from types import SimpleNamespace
from uuid import UUID
import json

import structlog

from lokilinux.ch import ClickHouseStore
from lokilinux.models.agent import Agent
from lokilinux.nats_topics import EVENT_NORMALIZED
from lokilinux.signals.detectors import (
    DETECTORS,
    METRIC_SAMPLE_EVENT_TYPE,
    RECOVERY_EVENT_TYPE,
    RECOVERY_RESOLVES_SIGNAL_TYPE,
    detect_metric_samples,
)
from lokilinux.signals.repository import SignalOccurrenceRepository
from lokilinux.signals.service import SignalService
from lokilinux.topology.service import ensure_host_node

logger = structlog.get_logger()


class SignalProcessorWorker:
    def __init__(self, nats_client, db_session_factory, cache, ch: ClickHouseStore) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache
        self.occurrences = SignalOccurrenceRepository(ch)

    async def start(self) -> None:
        await self.nats.subscribe(EVENT_NORMALIZED, cb=self._handle_normalized_event)
        logger.info("SignalProcessorWorker started")

    async def stop(self) -> None:
        await self.occurrences.flush()

    async def _auto_seed_host_node(self, db, host_id: str | None) -> None:
        """Cheap, idempotent: ensure a HOST topology node exists for this
        agent, named by its hostname. Best-effort — a lookup failure here
        must not break signal resolution, which already happened above."""
        agent_uuid = None
        if host_id:
            try:
                agent_uuid = UUID(str(host_id))
            except ValueError:
                return
        if agent_uuid is None:
            return
        try:
            agent = await db.get(Agent, agent_uuid)
            if agent is None:
                return
            await ensure_host_node(db, agent_id=agent.id, hostname=agent.hostname or agent.agent_id)
        except Exception:
            logger.warning("signal_processor.topology_seed_failed", host_id=host_id, exc_info=True)

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

    async def _process(self, event, *, tenant_id: str) -> None:
        try:
            async with self.db_factory() as db:
                svc = SignalService(db, self.nats, self.occurrences)

                if event.type == RECOVERY_EVENT_TYPE:
                    await svc.resolve_by_fingerprint(tenant_id, event.host_id, RECOVERY_RESOLVES_SIGNAL_TYPE)
                    await self._auto_seed_host_node(db, event.host_id)
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
