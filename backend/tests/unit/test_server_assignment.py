"""PATCH /servers/{id}/assignment — agent_group_id round-trip (agent-policy-
modernization plan Phase 3/4). category_id/project_id already worked; this
covers the field this plan's gap-closure added alongside them."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.agent_policy import AgentGroup


@pytest.mark.asyncio
async def test_set_assignment_persists_agent_group_id(client: AsyncClient, db_session):
    agent = Agent(
        agent_id=f"agent-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE, hostname="h1"
    )
    group = AgentGroup(name="test-group")
    db_session.add_all([agent, group])
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/servers/{agent.id}/assignment",
        json={"category_id": None, "project_id": None, "agent_group_id": str(group.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["agent_group_id"] == str(group.id)

    refreshed = (await db_session.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
    assert refreshed.agent_group_id == group.id


@pytest.mark.asyncio
async def test_set_assignment_clears_agent_group_id(client: AsyncClient, db_session):
    agent = Agent(
        agent_id=f"agent-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE, hostname="h2"
    )
    group = AgentGroup(name="test-group-2")
    db_session.add_all([agent, group])
    await db_session.flush()
    agent.agent_group_id = group.id
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/servers/{agent.id}/assignment",
        json={"category_id": None, "project_id": None, "agent_group_id": None},
    )
    assert resp.status_code == 200
    assert resp.json()["agent_group_id"] is None
