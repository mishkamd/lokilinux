"""
LokiLinux — CorrelationWorker: SIGNAL_DETECTED -> CorrelationEvaluator -> IncidentSink.

IncidentSink.open() takes the current message's `db` session (not stored on
the sink itself — the worker owns one session per message, IncidentService
needs to run inside it) plus the candidate. Task D2 (this commit) replaces
the Task C1 stub with IncidentServiceSink, wired by default; a caller can
still inject a different sink (tests, or a future no-op mode).
"""

from types import SimpleNamespace
import json

import structlog

from lokilinux.correlation.evaluator import CorrelationEvaluator, IncidentCandidate
from lokilinux.correlation.rules import RuleCache
from lokilinux.incidents.service import IncidentService
from lokilinux.nats_topics import SIGNAL_DETECTED, SIGNAL_RESOLVED
from lokilinux.utils import liveness

logger = structlog.get_logger()


class IncidentSink:
    async def open(self, db, candidate: IncidentCandidate) -> None:
        raise NotImplementedError


class NoOpIncidentSink(IncidentSink):
    """Drops candidates — useful for tests that only care about correlation,
    not incident creation."""

    async def open(self, db, candidate: IncidentCandidate) -> None:
        logger.info(
            "correlation.candidate_dropped_no_incident_sink",
            incident_type=candidate.rule.incident_type, score=candidate.score,
        )


class IncidentServiceSink(IncidentSink):
    def __init__(self, nats, cache, ch) -> None:
        self.nats = nats
        self.cache = cache
        self.ch = ch

    async def open(self, db, candidate: IncidentCandidate) -> None:
        # The rule was loaded for one tenant, so its tenant is the incident's tenant.
        await IncidentService(db, self.nats, self.cache, self.ch).open_from_candidate(
            candidate, tenant_id=candidate.rule.tenant_id
        )


class CorrelationWorker:
    def __init__(self, nats_client, db_session_factory, cache, ch, sink: IncidentSink | None = None) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.rule_cache = RuleCache()
        self.evaluator = CorrelationEvaluator(cache)
        self.sink = sink or IncidentServiceSink(nats_client, cache, ch)

    async def start(self) -> None:
        await self.nats.subscribe(SIGNAL_DETECTED, cb=self._handle_signal)
        await self.nats.subscribe(SIGNAL_RESOLVED, cb=self._handle_resolved)
        logger.info("CorrelationWorker started")

    async def _handle_resolved(self, msg) -> None:
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("correlation_worker.malformed_json", exc_info=True)
            return
        tenant_id = data.get("tenant_id") or "default"
        signal = SimpleNamespace(type=data.get("type"), host_id=data.get("host_id"))
        try:
            async with self.db_factory() as db:
                rules = await self.rule_cache.get_enabled_rules(db, tenant_id)
            await self.evaluator.on_signal_resolved(rules, signal, tenant_id=tenant_id)
        except Exception:
            logger.error("correlation_worker.resolve_failed", exc_info=True)

    async def _handle_signal(self, msg) -> None:
        liveness.beat("correlation_worker")  # no timer loop here: last signal handled is its pulse
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("correlation_worker.malformed_json", exc_info=True)
            return
        tenant_id = data.get("tenant_id") or "default"
        signal = SimpleNamespace(
            type=data.get("type"), host_id=data.get("host_id"), severity=data.get("severity")
        )
        try:
            async with self.db_factory() as db:
                rules = await self.rule_cache.get_enabled_rules(db, tenant_id)
                candidates = await self.evaluator.on_signal(rules, signal, tenant_id=tenant_id)
                for candidate in candidates:
                    await self.sink.open(db, candidate)
        except Exception:
            logger.error("correlation_worker.process_failed", exc_info=True)
