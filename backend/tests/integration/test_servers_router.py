"""
Integration tests for /api/v1/servers — list, detail, packages, maintenance,
and the new /vulnerabilities passthrough (bugfix: PK lookup, not agent_id).
"""

import uuid

import pytest
from httpx import AsyncClient

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.cve import CVE, AgentVulnerability, Package


async def _make_agent(db_session, **overrides) -> Agent:
    agent = Agent(
        agent_id=overrides.pop("agent_id", str(uuid.uuid4())),
        status=overrides.pop("status", AgentStatus.ACTIVE),
        hostname=overrides.pop("hostname", "web-01"),
        **overrides,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_list_servers(client: AsyncClient, db_session):
    await _make_agent(db_session, hostname="alpha")
    await _make_agent(db_session, hostname="beta")
    await db_session.commit()

    resp = await client.get("/api/v1/servers")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_server_by_pk(client: AsyncClient, db_session):
    agent = await _make_agent(db_session, hostname="gamma")
    await db_session.commit()

    resp = await client.get(f"/api/v1/servers/{agent.id}")
    assert resp.status_code == 200
    assert resp.json()["hostname"] == "gamma"


@pytest.mark.asyncio
async def test_get_server_404_on_invalid_pk(client: AsyncClient):
    resp = await client.get("/api/v1/servers/not-a-uuid")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_server_404_on_unknown_pk(client: AsyncClient):
    resp = await client.get(f"/api/v1/servers/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_server_packages(client: AsyncClient, db_session):
    agent = await _make_agent(db_session)
    db_session.add(Package(agent_id=agent.id, name="curl", version="8.1.0"))
    await db_session.commit()

    resp = await client.get(f"/api/v1/servers/{agent.id}/packages")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["name"] == "curl"


@pytest.mark.asyncio
async def test_toggle_maintenance(client: AsyncClient, db_session):
    agent = await _make_agent(db_session, status=AgentStatus.ACTIVE)
    await db_session.commit()

    resp = await client.post(f"/api/v1/servers/{agent.id}/maintenance")
    assert resp.status_code == 200
    assert resp.json()["status"] == "MAINTENANCE"

    resp = await client.post(f"/api/v1/servers/{agent.id}/maintenance")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_server_cve_count_reflects_open_findings_not_total(client: AsyncClient, db_session):
    """Regression: agents.cve_count was a denormalized column nothing ever
    wrote to (confirmed live: every row read 0). It's now computed from
    agent_vulnerabilities per response — and must count OPEN findings, not
    every row ever recorded (a RESOLVED finding shouldn't inflate the
    badge)."""
    agent = await _make_agent(db_session, hostname="cve-count-host")
    db_session.add(CVE(cve_id="CVE-2026-9200", cvss_v3_severity="HIGH"))
    db_session.add(CVE(cve_id="CVE-2026-9201", cvss_v3_severity="HIGH"))
    await db_session.flush()
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-9200", package_name="openssl", package_version="1.0",
        status="PATCH_AVAILABLE",
    ))
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-9201", package_name="curl", package_version="1.0",
        status="RESOLVED",
    ))
    await db_session.commit()

    list_resp = await client.get("/api/v1/servers")
    assert list_resp.status_code == 200
    item = next(i for i in list_resp.json()["items"] if i["id"] == str(agent.id))
    assert item["cve_count"] == 1

    detail_resp = await client.get(f"/api/v1/servers/{agent.id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["cve_count"] == 1


@pytest.mark.asyncio
async def test_server_vulnerabilities_uses_pk_not_agent_id(client: AsyncClient, db_session):
    """Bugfix regression: this endpoint used to look up Agent.agent_id (the
    identity string), while the frontend always sends the DB PK — causing a
    permanent 404 on the Vulnerabilities tab. It must accept the PK."""
    agent = await _make_agent(db_session)
    db_session.add(CVE(cve_id="CVE-2026-0001", cvss_v3_severity="HIGH"))
    await db_session.flush()
    db_session.add(AgentVulnerability(
        agent_id=agent.id,
        cve_id="CVE-2026-0001",
        package_name="openssl",
        package_version="3.0.1",
        severity="HIGH",
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/vulnerabilities/servers/{agent.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["cve_id"] == "CVE-2026-0001"


@pytest.mark.asyncio
async def test_server_vulnerabilities_404_for_unknown_server(client: AsyncClient):
    resp = await client.get(f"/api/v1/vulnerabilities/servers/{uuid.uuid4()}")
    assert resp.status_code == 404
