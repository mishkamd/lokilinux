import contextlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.topology.models import TopologyNode
from lokilinux.workers.signal_processor import SignalProcessorWorker


class _FakeCH:
    def __init__(self) -> None:
        self.inserted = []

    async def insert(self, table, data, column_names) -> None:
        self.inserted.append((table, data, column_names))


def _db_factory(db_session):
    @contextlib.asynccontextmanager
    async def factory():
        yield db_session

    return factory


def _msg(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps(payload).encode())


@pytest.mark.asyncio
async def test_normalized_host_unreachable_creates_signal(db_session, fake_cache, fake_nats):
    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_normalized_event(_msg({
        "type": "host.unreachable", "host_id": "host-1", "tenant_id": "default", "payload": {},
    }))
    await worker.occurrences.flush()

    subjects = [s for s, _ in fake_nats.published]
    assert "lokilinux.signals.detected" in subjects
    assert len(worker.occurrences.ch.inserted) == 1


@pytest.mark.asyncio
async def test_recovery_event_resolves_without_creating_a_signal(db_session, fake_cache, fake_nats):
    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_normalized_event(_msg({
        "type": "host.unreachable", "host_id": "host-2", "tenant_id": "default", "payload": {},
    }))
    fake_nats.published.clear()

    await worker._handle_normalized_event(_msg({
        "type": "host.heartbeat.ok", "host_id": "host-2", "tenant_id": "default", "payload": {},
    }))

    subjects = [s for s, _ in fake_nats.published]
    assert subjects == ["lokilinux.signals.resolved"]


@pytest.mark.asyncio
async def test_recovery_event_auto_seeds_topology_host_node(db_session, fake_cache, fake_nats):
    agent = Agent(agent_id=str(uuid4()), status=AgentStatus.ACTIVE, hostname="web-1")
    db_session.add(agent)
    await db_session.flush()

    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_normalized_event(_msg({
        "type": "host.heartbeat.ok", "host_id": str(agent.id), "tenant_id": "default", "payload": {},
    }))

    rows = (await db_session.execute(select(TopologyNode).where(TopologyNode.agent_id == agent.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == "HOST"
    assert rows[0].name == "web-1"


@pytest.mark.asyncio
async def test_recovery_event_with_non_uuid_host_id_skips_topology_seed_without_raising(db_session, fake_cache, fake_nats):
    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_normalized_event(_msg({
        "type": "host.heartbeat.ok", "host_id": "host-2", "tenant_id": "default", "payload": {},
    }))  # "host-2" isn't a UUID — must not raise, just skip the topology seed


@pytest.mark.asyncio
async def test_unknown_event_type_is_ignored(db_session, fake_cache, fake_nats):
    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_normalized_event(_msg({
        "type": "some.unrelated.type", "host_id": "host-3", "tenant_id": "default", "payload": {},
    }))
    assert fake_nats.published == []


@pytest.mark.asyncio
async def test_malformed_json_does_not_raise(db_session, fake_cache, fake_nats):
    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_normalized_event(SimpleNamespace(data=b"{not-json"))  # must not raise
    assert fake_nats.published == []


@pytest.mark.asyncio
async def test_compliance_drift_is_wrapped_and_detected(db_session, fake_cache, fake_nats):
    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_drift(_msg({
        "agent_id": "host-4", "severity": "CRITICAL", "resource_id": "etc-passwd",
    }))

    subjects = [s for s, _ in fake_nats.published]
    assert "lokilinux.signals.detected" in subjects


@pytest.mark.asyncio
async def test_compliance_drift_low_severity_produces_no_signal(db_session, fake_cache, fake_nats):
    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_drift(_msg({"agent_id": "host-5", "severity": "LOW"}))
    assert fake_nats.published == []


@pytest.mark.asyncio
async def test_metric_sample_cpu_needs_two_samples_before_signal(db_session, fake_cache, fake_nats):
    worker = SignalProcessorWorker(fake_nats, _db_factory(db_session), fake_cache, _FakeCH())
    await worker._handle_normalized_event(_msg({
        "type": "metric.sample", "host_id": "host-6", "tenant_id": "default", "payload": {"cpu": 95},
    }))
    assert fake_nats.published == []

    await worker._handle_normalized_event(_msg({
        "type": "metric.sample", "host_id": "host-6", "tenant_id": "default", "payload": {"cpu": 95},
    }))
    subjects = [s for s, _ in fake_nats.published]
    assert "lokilinux.signals.detected" in subjects
