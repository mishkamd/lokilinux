"""Observability failure matrix (plan G3) — the rows that are genuinely
backend-observable without new test infrastructure this pass didn't build:

- NATS redelivery dedup (G3-2): confirms EventProcessorWorker._handle_raw's
  existing cache.set_nx dedup actually stops a duplicate delivery from
  double-inserting — this is proving already-correct code, not new logic.
- ClickHouse down, incident lifecycle unaffected (G3-4): drives a real
  IncidentService.open_from_candidate against the test Postgres while
  incident_evidence's ClickHouse write fails every time, confirming the
  incident row still commits.
- Postgres blip during correlation (G3-5, REVISED after a spike — see the
  plan file's G3-5 section): the original scope ("NATS retention replays")
  assumed a JetStream consumer that doesn't exist — `main.py` connects
  plain-core NATS (`nats.connect`), and grep across the whole backend found
  zero JetStream consumers of the streams `eventbus.py` provisions. What's
  actually tested here instead: (1) a Postgres blip during
  CorrelationWorker._handle_signal is swallowed without crashing the
  worker, and (2) the SIGNALS JetStream stream (passive 24h archive) is
  configured to cover SIGNAL_DETECTED's subject — a structural check that
  the archival mechanism exists, since proving it works at runtime would
  require a live NATS server this test suite has no fixture for. No
  automated replay of an archived-but-unprocessed message exists today;
  this is a documented gap, not something this pass builds.

Redis-down fail-open is NOT re-tested here — already covered at the unit
level in tests/unit/test_correlation_evaluator.py (G3-3).
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lokilinux.correlation.evaluator import IncidentCandidate
from lokilinux.events.fingerprint import fingerprint
from lokilinux.incidents.service import IncidentService
from lokilinux.signals.models import CorrelationRule, Signal
from lokilinux.workers.correlation_worker import CorrelationWorker
from lokilinux.workers.event_processor import EventProcessorWorker


class _DedupCache:
    """Just enough of RedisCache for EventProcessorWorker: real first-writer-
    wins set_nx semantics, so a duplicate delivery is actually rejected the
    same way the real Redis SETNX would reject it."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    async def set_nx(self, key: str, ttl: int) -> bool:
        if key in self._keys:
            return False
        self._keys.add(key)
        return True


class _InsertingFakeCH:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, list, list]] = []

    async def insert(self, table, data, column_names) -> None:
        self.inserted.append((table, data, column_names))


class _FailingCH:
    """Every insert() raises — for the incident_evidence-write-fails case."""

    async def insert(self, table, data, column_names) -> None:
        raise RuntimeError("clickhouse unreachable")


class _RecordingNats:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, data: bytes) -> None:
        self.published.append((subject, data))


def _raw_event_bytes(event_id: str, **overrides) -> bytes:
    payload = {
        "schema_version": 1,
        "event_id": event_id,
        "tenant_id": "default",
        "source": "agent",
        "type": "kernel.panic",
        "severity": "CRITICAL",
        "host_id": "host-1",
        "service": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {},
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


@pytest.mark.asyncio
async def test_nats_redelivery_dedup_inserts_once():
    cache = _DedupCache()
    ch = _InsertingFakeCH()
    worker = EventProcessorWorker(nats_client=_RecordingNats(), cache=cache, ch=ch)

    event_id = str(uuid4())
    msg = SimpleNamespace(data=_raw_event_bytes(event_id))

    await worker._handle_raw(msg)
    await worker._handle_raw(msg)  # simulated redelivery — same event_id
    await worker.repository.flush()

    assert len(ch.inserted) == 1
    _, rows, columns = ch.inserted[0]
    assert len(rows) == 1  # not 2 — the redelivered copy never reached the buffer
    assert rows[0][columns.index("event_id")] == event_id


@pytest.mark.asyncio
async def test_clickhouse_down_incident_lifecycle_unaffected(db_session):
    tenant_id = "default"
    host_id = "host-evidence-1"
    fp = fingerprint(tenant_id, host_id, "cpu.high", None)
    now = datetime.now(timezone.utc)
    signal = Signal(
        tenant_id=tenant_id,
        type="cpu.high",
        severity="CRITICAL",
        status="OPEN",
        fingerprint=fp,
        occurrence_count=1,
        first_seen=now,
        last_seen=now,
    )
    db_session.add(signal)
    await db_session.flush()

    rule = CorrelationRule(
        tenant_id=tenant_id,
        name="cpu-exhaustion-test",
        window_seconds=300,
        group_by=["host_id"],
        conditions=[{"signal": "cpu.high", "weight": 20}],
        threshold_score=20,
        incident_type="resource_exhaustion",
        incident_severity="CRITICAL",
    )
    db_session.add(rule)
    await db_session.flush()

    candidate = IncidentCandidate(
        rule=rule,
        group_key="grp-1",
        group_values={"host_id": host_id},
        member_types=["cpu.high"],
        score=20,
        root_signal_type="cpu.high",
    )

    svc = IncidentService(db_session, _RecordingNats(), _DedupCache(), _FailingCH())
    incident = await svc.open_from_candidate(candidate, tenant_id=tenant_id)

    assert incident.id is not None
    assert incident.status == "OPEN"
    assert incident.type == "resource_exhaustion"


@pytest.mark.asyncio
async def test_postgres_blip_during_correlation_swallowed_not_crashed():
    class _ExplodingDBFactory:
        def __call__(self):
            raise RuntimeError("postgres connection blip")

    worker = CorrelationWorker(
        nats_client=_RecordingNats(),
        db_session_factory=_ExplodingDBFactory(),
        cache=_DedupCache(),
        ch=_InsertingFakeCH(),
    )
    msg = SimpleNamespace(
        data=json.dumps({"type": "cpu.high", "host_id": "host-1", "severity": "CRITICAL"}).encode()
    )

    # Must not raise — CorrelationWorker._handle_signal's own try/except
    # around the db_factory()/evaluator/sink path is what's under test.
    await worker._handle_signal(msg)


def test_signals_stream_configured_for_signal_detected_subject():
    """Structural check standing in for a live-runtime replay proof this
    suite has no NATS fixture for: the SIGNALS JetStream stream (passive
    24h archive, eventbus.py) is at least configured to capture
    SIGNAL_DETECTED's subject — so a Postgres-blip-lost signal is
    recoverable from the stream even though nothing replays it
    automatically today."""
    from lokilinux.eventbus import _STREAM_CONFIGS
    from lokilinux.nats_topics import SIGNAL_DETECTED

    signals_stream = next((c for c in _STREAM_CONFIGS if c.name == "SIGNALS"), None)
    assert signals_stream is not None, "no SIGNALS stream configured in eventbus.py"

    prefix = SIGNAL_DETECTED.rsplit(".", 1)[0] + "."
    assert any(
        subj.startswith(prefix.rstrip(">").rstrip(".")) for subj in signals_stream.subjects
    ), f"SIGNALS stream subjects {signals_stream.subjects} do not cover {SIGNAL_DETECTED}"
