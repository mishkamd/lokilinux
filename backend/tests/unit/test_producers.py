"""
Task A5 producer wiring — HeartbeatMonitorWorker emits host.unreachable
alongside the existing AGENT_UNHEALTHY publish, gated by the observability
pipeline kill switch (settings_schema "observability.event_pipeline_enabled").
"""

import contextlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import lokilinux.workers.heartbeat_monitor as heartbeat_monitor
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.workers.heartbeat_monitor import HeartbeatMonitorWorker


async def _make_stale_agent(db_session) -> Agent:
    agent = Agent(
        agent_id=str(uuid.uuid4()),
        status=AgentStatus.ACTIVE,
        hostname="stale-host",
        last_heartbeat=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


def _db_factory(db_session):
    @contextlib.asynccontextmanager
    async def factory():
        yield db_session

    return factory


@pytest.mark.asyncio
async def test_sweep_emits_host_unreachable_when_pipeline_enabled(db_session, fake_cache, fake_nats, monkeypatch):
    agent = await _make_stale_agent(db_session)
    emitted = []

    async def _fake_emit(_nats, source, type_, **kwargs):
        emitted.append((source, type_, kwargs))

    async def _enabled(_cache, _db):
        return True

    monkeypatch.setattr(heartbeat_monitor, "emit", _fake_emit)
    monkeypatch.setattr(heartbeat_monitor, "is_pipeline_enabled", _enabled)

    worker = HeartbeatMonitorWorker(fake_nats, _db_factory(db_session), fake_cache)
    await worker._sweep()

    assert len(emitted) == 1
    source, type_, kwargs = emitted[0]
    assert source == "agent"
    assert type_ == "host.unreachable"
    assert kwargs["host_id"] == str(agent.id)
    assert kwargs["severity"] == "CRITICAL"


@pytest.mark.asyncio
async def test_sweep_skips_emit_when_pipeline_disabled(db_session, fake_cache, fake_nats, monkeypatch):
    await _make_stale_agent(db_session)
    emitted = []

    async def _fake_emit(_nats, source, type_, **kwargs):
        emitted.append((source, type_, kwargs))

    async def _disabled(_cache, _db):
        return False

    monkeypatch.setattr(heartbeat_monitor, "emit", _fake_emit)
    monkeypatch.setattr(heartbeat_monitor, "is_pipeline_enabled", _disabled)

    worker = HeartbeatMonitorWorker(fake_nats, _db_factory(db_session), fake_cache)
    await worker._sweep()

    assert emitted == []
    # legacy alert path is unaffected by the kill switch
    assert len(fake_nats.published) == 1
