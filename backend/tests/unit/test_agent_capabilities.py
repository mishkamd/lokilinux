"""Heartbeat capability report is stored on the agent (ROADMAP R5)."""

import uuid

import pytest

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.services.agent_service import AgentService


@pytest.mark.asyncio
async def test_heartbeat_stores_reported_capabilities(db_session, fake_cache):
    agent = Agent(
        agent_id=f"cap-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE,
        hostname=f"cap-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(agent)
    await db_session.flush()
    assert agent.capabilities is None  # never reported

    await AgentService(db_session, fake_cache).update_heartbeat(
        agent.agent_id, {"capabilities": ["SERVICE", "FILE"]},
    )

    assert agent.capabilities == ["SERVICE", "FILE"]


@pytest.mark.asyncio
async def test_capability_list_is_bounded(db_session, fake_cache):
    agent = Agent(
        agent_id=f"cap-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE,
        hostname=f"cap-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(agent)
    await db_session.flush()

    await AgentService(db_session, fake_cache).update_heartbeat(
        agent.agent_id, {"capabilities": ["X" * 200] + [f"C{i}" for i in range(100)]},
    )

    assert len(agent.capabilities) == 32
    assert len(agent.capabilities[0]) == 64
