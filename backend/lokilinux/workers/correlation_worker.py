"""
LokiLinux — CorrelationWorker: SIGNAL_DETECTED -> CorrelationEvaluator -> IncidentSink.

IncidentSink is a stub interface for Task C1 — Task D2 (Phase D, not yet
written) swaps in the real IncidentService without this worker changing
again; `sink=None` defaults to a no-op sink so this worker is fully usable
(rules load, windows accumulate, candidates get computed and just dropped)
before Phase D exists.
"""

from types import SimpleNamespace
import json

import structlog

from lokilinux.correlation.evaluator import CorrelationEvaluator, IncidentCandidate
from lokilinux.correlation.rules import RuleCache
from lokilinux.nats_topics import SIGNAL_DETECTED

logger = structlog.get_logger()


class IncidentSink:
    """Stub — replaced by IncidentService in Task D2."""

    async def open(self, candidate: IncidentCandidate) -> None:
        logger.info(
            "correlation.candidate_dropped_no_incident_sink",
            incident_type=candidate.rule.incident_type, score=candidate.score,
        )


class CorrelationWorker:
    def __init__(self, nats_client, db_session_factory, cache, sink: IncidentSink | None = None) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.rule_cache = RuleCache()
        self.evaluator = CorrelationEvaluator(cache)
        self.sink = sink or IncidentSink()

    async def start(self) -> None:
        await self.nats.subscribe(SIGNAL_DETECTED, cb=self._handle_signal)
        logger.info("CorrelationWorker started")

    async def _handle_signal(self, msg) -> None:
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("correlation_worker.malformed_json", exc_info=True)
            return
        signal = SimpleNamespace(type=data.get("type"), host_id=data.get("host_id"))
        try:
            async with self.db_factory() as db:
                rules = await self.rule_cache.get_enabled_rules(db)
                candidates = await self.evaluator.on_signal(rules, signal)
                for candidate in candidates:
                    await self.sink.open(candidate)
        except Exception:
            logger.error("correlation_worker.process_failed", exc_info=True)
