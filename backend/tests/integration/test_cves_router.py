"""Integration tests for /api/v1/vulnerabilities — global CVE list + detail."""

import pytest
from httpx import AsyncClient

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.cve import CVE, AgentVulnerability


@pytest.mark.asyncio
async def test_list_vulnerabilities(client: AsyncClient, db_session):
    db_session.add(CVE(cve_id="CVE-2026-1000", cvss_v3_score=9.8, cvss_v3_severity="CRITICAL"))
    db_session.add(CVE(cve_id="CVE-2026-1001", cvss_v3_score=4.0, cvss_v3_severity="MEDIUM"))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


@pytest.mark.asyncio
async def test_list_vulnerabilities_filters_by_severity(client: AsyncClient, db_session):
    db_session.add(CVE(cve_id="CVE-2026-2000", cvss_v3_severity="CRITICAL"))
    db_session.add(CVE(cve_id="CVE-2026-2001", cvss_v3_severity="LOW"))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities", params={"severity": "CRITICAL"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["cve_id"] == "CVE-2026-2000"


@pytest.mark.asyncio
async def test_get_cve_detail(client: AsyncClient, db_session):
    db_session.add(CVE(cve_id="CVE-2026-3000", title="Test CVE", cvss_v3_severity="HIGH"))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities/CVE-2026-3000")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test CVE"


@pytest.mark.asyncio
async def test_get_cve_detail_404(client: AsyncClient):
    resp = await client.get("/api/v1/vulnerabilities/CVE-9999-9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_vulnerabilities_summary_and_total(client: AsyncClient, db_session):
    db_session.add(CVE(cve_id="CVE-2026-4000", cvss_v3_severity="CRITICAL"))
    db_session.add(CVE(cve_id="CVE-2026-4001", cvss_v3_severity="CRITICAL"))
    db_session.add(CVE(cve_id="CVE-2026-4002", cvss_v3_severity="LOW"))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities", params={"limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["summary"]["CRITICAL"] == 2
    assert body["summary"]["LOW"] == 1


@pytest.mark.asyncio
async def test_list_vulnerabilities_search(client: AsyncClient, db_session):
    db_session.add(CVE(cve_id="CVE-2026-5000", title="Buffer overflow in libfoo", cvss_v3_severity="HIGH"))
    db_session.add(CVE(cve_id="CVE-2026-5001", title="Unrelated issue", cvss_v3_severity="HIGH"))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities", params={"search": "buffer overflow"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["cve_id"] == "CVE-2026-5000"


@pytest.mark.asyncio
async def test_list_vulnerabilities_exploited_only(client: AsyncClient, db_session):
    db_session.add(CVE(cve_id="CVE-2026-6000", cvss_v3_severity="HIGH", is_actively_exploited=True))
    db_session.add(CVE(cve_id="CVE-2026-6001", cvss_v3_severity="HIGH", is_actively_exploited=False))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities", params={"exploited_only": True})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["cve_id"] == "CVE-2026-6000"


@pytest.mark.asyncio
async def test_list_vulnerabilities_affected_count(client: AsyncClient, db_session):
    db_session.add(CVE(cve_id="CVE-2026-7000", cvss_v3_severity="HIGH"))
    agent = Agent(agent_id="agent-affected", status=AgentStatus.ACTIVE, hostname="h1")
    db_session.add(agent)
    await db_session.flush()
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-7000", package_name="openssl", package_version="1.0",
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities")
    assert resp.status_code == 200
    item = next(i for i in resp.json()["items"] if i["cve_id"] == "CVE-2026-7000")
    assert item["affected_count"] == 1
