"""
Unit tests for AlertService.create_alert dedup.

Regression coverage: HeartbeatMonitorWorker sweeps every 60s and republishes
lokilinux.agent.unhealthy for the same stale agent every cycle. Without
dedup, create_alert inserted a fresh row each time — confirmed live, one
flapping agent had accumulated 64 identical AGENT_OFFLINE alerts.
"""

import uuid

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.alert import Alert
from lokilinux.services.alert_service import AlertService


async def _make_agent(db_session) -> Agent:
    agent = Agent(agent_id=str(uuid.uuid4()), status=AgentStatus.INACTIVE, hostname="flappy")
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_create_alert_dedups_same_agent_and_type(db_session, fake_nats):
    agent = await _make_agent(db_session)
    svc = AlertService(db_session, fake_nats)

    first = await svc.create_alert(
        title="Agent flappy UNHEALTHY", description="x", severity="HIGH",
        agent_id=agent.id, alert_type="AGENT_OFFLINE",
    )
    second = await svc.create_alert(
        title="Agent flappy UNHEALTHY", description="x", severity="HIGH",
        agent_id=agent.id, alert_type="AGENT_OFFLINE",
    )

    assert first is not None
    assert second is None  # deduped — no second row, no re-notification

    rows = (await db_session.execute(select(Alert).where(Alert.agent_id == agent.id))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_create_alert_allows_different_agents(db_session, fake_nats):
    agent1 = await _make_agent(db_session)
    agent2 = await _make_agent(db_session)
    svc = AlertService(db_session, fake_nats)

    await svc.create_alert(title="a", description="x", severity="HIGH", agent_id=agent1.id, alert_type="AGENT_OFFLINE")
    await svc.create_alert(title="b", description="x", severity="HIGH", agent_id=agent2.id, alert_type="AGENT_OFFLINE")

    rows = (await db_session.execute(select(Alert))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_create_alert_allows_new_one_after_prior_resolved(db_session, fake_nats):
    """A resolved alert must not block a genuinely new occurrence — the
    partial unique index only covers status='ACTIVE' rows."""
    agent = await _make_agent(db_session)
    svc = AlertService(db_session, fake_nats)

    first = await svc.create_alert(
        title="a", description="x", severity="HIGH", agent_id=agent.id, alert_type="AGENT_OFFLINE",
    )
    assert first is not None
    first.status = "RESOLVED"
    await db_session.commit()

    second = await svc.create_alert(
        title="a again", description="x", severity="HIGH", agent_id=agent.id, alert_type="AGENT_OFFLINE",
    )
    assert second is not None

    rows = (await db_session.execute(select(Alert).where(Alert.agent_id == agent.id))).scalars().all()
    assert len(rows) == 2
