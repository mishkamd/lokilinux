"""Integration tests for /api/v1/vulnerabilities — global CVE list + detail."""

import pytest
from httpx import AsyncClient

from lokilinux.models.cve import CVE


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
