import contextlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from lokilinux.correlation.rules import ensure_default_rules
from lokilinux.incidents.models import Incident
from lokilinux.workers.correlation_worker import (
    CorrelationWorker,
    IncidentCandidate,
    IncidentSink,
    NoOpIncidentSink,
)


class _FakeZSetCache:
    def __init__(self) -> None:
        self._zsets: dict = {}
        self._locks: set = set()

    async def zadd(self, key, member, score) -> None:
        self._zsets.setdefault(key, {})[member] = score

    async def zrangebyscore(self, key, min_score, max_score) -> list:
        return [m for m, s in self._zsets.get(key, {}).items() if min_score <= s <= max_score]

    async def expire(self, key, ttl) -> None:
        pass

    async def set_nx(self, key, ttl) -> bool:
        if key in self._locks:
            return False
        self._locks.add(key)
        return True


class _RecordingSink(IncidentSink):
    def __init__(self) -> None:
        self.opened: list[IncidentCandidate] = []

    async def open(self, db, candidate: IncidentCandidate) -> None:
        self.opened.append(candidate)


def _db_factory(db_session):
    @contextlib.asynccontextmanager
    async def factory():
        yield db_session

    return factory


def _msg(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps(payload).encode())


@pytest.mark.asyncio
async def test_reaching_threshold_opens_via_sink(db_session, fake_nats):
    await ensure_default_rules(db_session)
    sink = _RecordingSink()
    worker = CorrelationWorker(fake_nats, _db_factory(db_session), _FakeZSetCache(), sink=sink)

    await worker._handle_signal(_msg({"type": "cpu.high", "host_id": "host-1"}))
    await worker._handle_signal(_msg({"type": "load.high", "host_id": "host-1"}))
    await worker._handle_signal(_msg({"type": "http.latency.high", "host_id": "host-1"}))  # 20+20+25=65

    assert len(sink.opened) == 1
    assert sink.opened[0].rule.incident_type == "application_degradation"


@pytest.mark.asyncio
async def test_below_threshold_never_opens(db_session, fake_nats):
    await ensure_default_rules(db_session)
    sink = _RecordingSink()
    worker = CorrelationWorker(fake_nats, _db_factory(db_session), _FakeZSetCache(), sink=sink)

    await worker._handle_signal(_msg({"type": "cpu.high", "host_id": "host-2"}))
    assert sink.opened == []


@pytest.mark.asyncio
async def test_default_sink_creates_a_real_incident(db_session, fake_nats):
    """sink=None wires IncidentServiceSink by default (Task D2) — a threshold
    crossing without an explicit sink actually opens an Incident row, not a
    no-op drop."""
    await ensure_default_rules(db_session)
    worker = CorrelationWorker(fake_nats, _db_factory(db_session), _FakeZSetCache())

    await worker._handle_signal(_msg({"type": "cpu.high", "host_id": "host-3"}))
    await worker._handle_signal(_msg({"type": "load.high", "host_id": "host-3"}))
    await worker._handle_signal(_msg({"type": "http.latency.high", "host_id": "host-3"}))

    rows = (await db_session.execute(select(Incident))).scalars().all()
    assert len(rows) == 1
    assert rows[0].type == "application_degradation"


@pytest.mark.asyncio
async def test_explicit_noop_sink_drops_without_raising(db_session, fake_nats):
    await ensure_default_rules(db_session)
    worker = CorrelationWorker(fake_nats, _db_factory(db_session), _FakeZSetCache(), sink=NoOpIncidentSink())

    await worker._handle_signal(_msg({"type": "cpu.high", "host_id": "host-4"}))
    await worker._handle_signal(_msg({"type": "load.high", "host_id": "host-4"}))
    await worker._handle_signal(_msg({"type": "http.latency.high", "host_id": "host-4"}))

    rows = (await db_session.execute(select(Incident))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_malformed_json_does_not_raise(db_session, fake_nats):
    worker = CorrelationWorker(fake_nats, _db_factory(db_session), _FakeZSetCache())
    await worker._handle_signal(SimpleNamespace(data=b"{not-json"))  # must not raise
