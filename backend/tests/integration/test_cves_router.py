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
async def test_summary_severity_reads_cve_catalog_not_stale_finding_snapshot(
    client: AsyncClient, db_session
):
    """agent_vulnerabilities.severity is set once at scan time from the
    distro advisory and never updated when the NVD enrichment worker later
    corrects cves.cvss_v3_severity — the summary must count by the catalog's
    current severity, not the stale per-finding column, or a re-classified
    CRITICAL silently reports as whatever it was before enrichment."""
    import uuid

    from lokilinux.models.agent import Agent
    from lokilinux.models.cve import AgentVulnerability

    agent_id = uuid.uuid4()
    db_session.add(Agent(id=agent_id, agent_id=str(agent_id), hostname="sev-drift-host"))
    db_session.add(CVE(cve_id="CVE-2026-9000", cvss_v3_severity="CRITICAL"))
    await db_session.commit()

    db_session.add(AgentVulnerability(
        # severity="HIGH" is stale here — scan-time value, before enrichment
        agent_id=agent_id, cve_id="CVE-2026-9000", package_name="kernel",
        package_version="1.0", severity="HIGH",
        status="PATCH_AVAILABLE",
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["critical"] == 1
    assert body["high"] == 0


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
async def test_server_vulnerabilities_returns_cvss_score_from_catalog(client: AsyncClient, db_session):
    """Regression: agent_vulnerabilities.cvss_score is a snapshot column
    nothing ever populates (confirmed live: 0/2068 rows had it set) — the
    per-server endpoint must read cves.cvss_v3_score instead, the same
    column the NVD enrichment worker keeps current, or the CVSS column in
    the UI renders "—" forever."""
    agent = Agent(agent_id="agent-cvss", status=AgentStatus.ACTIVE, hostname="cvss-host")
    db_session.add(agent)
    db_session.add(CVE(cve_id="CVE-2026-8000", cvss_v3_score=8.2, cvss_v3_severity="HIGH"))
    await db_session.flush()
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-8000", package_name="openssl", package_version="1.0",
        # cvss_score deliberately left unset — matches every real row.
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/vulnerabilities/servers/{agent.id}")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["cvss_score"] == 8.2


@pytest.mark.asyncio
async def test_server_vulnerabilities_defaults_to_open_only(client: AsyncClient, db_session):
    """Regression: the tab used to show every finding ever recorded,
    RESOLVED included (confirmed live: 1566 rows for one host, 82 actually
    open) — default must be open-only, matching /vulnerabilities/summary's
    own counting rule, with include_resolved=true as the escape hatch."""
    agent = Agent(agent_id="agent-resolved-mix", status=AgentStatus.ACTIVE, hostname="resolved-host")
    db_session.add(agent)
    db_session.add(CVE(cve_id="CVE-2026-8100", cvss_v3_severity="HIGH"))
    db_session.add(CVE(cve_id="CVE-2026-8101", cvss_v3_severity="HIGH"))
    await db_session.flush()
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-8100", package_name="openssl", package_version="1.0",
        status="PATCH_AVAILABLE",
    ))
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-8101", package_name="curl", package_version="1.0",
        status="RESOLVED",
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/vulnerabilities/servers/{agent.id}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["cve_id"] == "CVE-2026-8100"

    resp_all = await client.get(f"/api/v1/vulnerabilities/servers/{agent.id}", params={"include_resolved": True})
    assert resp_all.status_code == 200
    assert len(resp_all.json()["items"]) == 2


@pytest.mark.asyncio
async def test_list_vulnerabilities_affected_count(client: AsyncClient, db_session):
    """Regression: the same CVE hitting two packages on one host (real,
    confirmed live: CVE-2026-59858 via both vim-minimal and vim-filesystem
    on one agent) must count as 1 server affected, not 2 — affected_count
    means distinct agents, not (cve, package) rows."""
    db_session.add(CVE(cve_id="CVE-2026-7000", cvss_v3_severity="HIGH"))
    agent = Agent(agent_id="agent-affected", status=AgentStatus.ACTIVE, hostname="h1")
    db_session.add(agent)
    await db_session.flush()
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-7000", package_name="openssl", package_version="1.0",
    ))
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-7000", package_name="openssl-libs", package_version="1.0",
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/vulnerabilities")
    assert resp.status_code == 200
    item = next(i for i in resp.json()["items"] if i["cve_id"] == "CVE-2026-7000")
    assert item["affected_count"] == 1
