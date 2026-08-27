"""Integration tests for /api/v1/configuration — Enterprise Compliance
plan U2 Task 2. Thin alias delegates: content must be byte-identical to
the /compliance/* equivalent, since they call the exact same handler."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.drift import DriftEvent


@pytest.mark.asyncio
async def test_configuration_baselines_matches_compliance_baselines(client: AsyncClient):
    await client.post(
        "/api/v1/compliance/baselines",
        json={
            "name": "U2 alias test baseline",
            "scope_type": "GLOBAL",
            "scope_selector": {},
            "expected_state": {"sshd": {"PermitRootLogin": "no"}},
        },
    )

    compliance_resp = await client.get("/api/v1/compliance/baselines")
    configuration_resp = await client.get("/api/v1/configuration/baselines")

    assert compliance_resp.status_code == configuration_resp.status_code == 200
    assert configuration_resp.json() == compliance_resp.json()


@pytest.mark.asyncio
async def test_configuration_drift_matches_compliance_drift(
    client: AsyncClient, db_session: AsyncSession
):
    agent = Agent(
        agent_id=f"test-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname="host-u2",
    )
    db_session.add(agent)
    await db_session.flush()
    db_session.add(
        DriftEvent(
            time=datetime.now(timezone.utc),
            agent_id=agent.id,
            id=uuid.uuid4(),
            domain="sshd",
            compared_against="BASELINE",
            severity="HIGH",
            change_type="MODIFIED",
            summary="U2 alias test drift",
            status="OPEN",
        )
    )
    await db_session.commit()

    compliance_resp = await client.get("/api/v1/compliance/drift-events")
    configuration_resp = await client.get("/api/v1/configuration/drift")

    assert compliance_resp.status_code == configuration_resp.status_code == 200
    assert configuration_resp.json() == compliance_resp.json()


@pytest.mark.asyncio
async def test_configuration_router_has_no_mutation_routes(client: AsyncClient):
    """Read-only per plan U2 (Task 1: "reusing compliance components where
    read-only") — acknowledge/suppress/resolve stay /compliance/*-only."""
    resp = await client.post(
        "/api/v1/configuration/drift/00000000-0000-0000-0000-000000000000/acknowledge"
    )
    assert resp.status_code == 404
