"""Integration tests for /api/v1/dashboard — summary + trends aggregates."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from lokilinux.models.agent import Agent, AgentHealth, AgentStatus
from lokilinux.models.alert import Alert
from lokilinux.models.cve import CVE, AgentVulnerability
from lokilinux.models.job import Job, JobStatus


@pytest.mark.asyncio
async def test_summary_health_averages_latest_snapshot_per_agent(
    client: AsyncClient, db_session
):
    agent = Agent(
        id=uuid.uuid4(), agent_id="agent-health-1", hostname="h1",
        status=AgentStatus.ACTIVE,
    )
    db_session.add(agent)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    # stale snapshot — should be ignored in favor of the newer one
    db_session.add(AgentHealth(
        agent_id=agent.id, cpu_usage=10.0, memory_usage=10.0, disk_usage=10.0,
        network_latency_ms=1.0, recorded_at=now - timedelta(hours=1),
    ))
    db_session.add(AgentHealth(
        agent_id=agent.id, cpu_usage=50.0, memory_usage=60.0, disk_usage=70.0,
        network_latency_ms=5.0, recorded_at=now,
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    health = resp.json()["health"]
    assert health["cpu_usage"] == 50.0
    assert health["memory_usage"] == 60.0
    assert health["disk_usage"] == 70.0
    assert health["network_latency_ms"] == 5.0


@pytest.mark.asyncio
async def test_summary_vuln_by_severity_reads_cve_catalog_not_stale_finding_snapshot(
    client: AsyncClient, db_session
):
    """Same drift as /vulnerabilities/summary — the widget must count by
    cves.cvss_v3_severity, not the scan-time agent_vulnerabilities.severity
    snapshot the NVD enrichment worker never touches."""
    agent = Agent(id=uuid.uuid4(), agent_id="agent-sev-drift", hostname="h-sev")
    db_session.add(agent)
    db_session.add(CVE(cve_id="CVE-2026-9100", cvss_v3_severity="CRITICAL"))
    await db_session.commit()

    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-9100", package_name="kernel",
        package_version="1.0", severity="HIGH", status="PATCH_AVAILABLE",
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    by_severity = resp.json()["vulnerabilities"]["by_severity"]
    assert by_severity.get("CRITICAL") == 1
    assert by_severity.get("HIGH") is None


@pytest.mark.asyncio
async def test_summary_vuln_by_severity_matches_status_not_is_remediated(
    client: AsyncClient, db_session
):
    """An ACCEPTED_RISK finding is a recorded decision, not open exposure —
    it must NOT be counted here, same as /vulnerabilities/summary and
    /cves/top-resources. Filtering on is_remediated=False alone (the old
    behavior) would have wrongly counted it, since accepted-risk findings
    are never marked is_remediated=True (agent_service.py's ingestion
    comment states this explicitly)."""
    agent = Agent(id=uuid.uuid4(), agent_id="agent-accepted-risk", hostname="h-ar")
    db_session.add(agent)
    db_session.add(CVE(cve_id="CVE-2026-9200", cvss_v3_severity="LOW"))
    await db_session.commit()

    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2026-9200", package_name="curl",
        package_version="1.0", severity="LOW", status="ACCEPTED_RISK",
        is_remediated=False,
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    by_severity = resp.json()["vulnerabilities"]["by_severity"]
    assert by_severity.get("LOW") is None


@pytest.mark.asyncio
async def test_summary_health_null_when_no_snapshots(client: AsyncClient):
    resp = await client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    health = resp.json()["health"]
    assert health["cpu_usage"] is None
    assert health["memory_usage"] is None


@pytest.mark.asyncio
async def test_trends_servers_counts_registrations_before_each_day(
    client: AsyncClient, db_session
):
    old_agent = Agent(
        id=uuid.uuid4(), agent_id="agent-old", hostname="old",
        status=AgentStatus.ACTIVE,
        registered_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db_session.add(old_agent)
    await db_session.commit()

    resp = await client.get("/api/v1/dashboard/trends", params={"range": "7d"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["servers"]) > 0
    # registered 10 days ago — present in every bucket of a 7d window
    assert all(point["total"] >= 1 for point in body["servers"])


@pytest.mark.asyncio
async def test_trends_jobs_bucketed_by_status(client: AsyncClient, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(Job(name="ok", job_type="PACKAGE_UPDATE", target_servers={},
                        status=JobStatus.COMPLETED, created_at=now))
    db_session.add(Job(name="bad", job_type="PACKAGE_UPDATE", target_servers={},
                        status=JobStatus.FAILED, created_at=now))
    db_session.add(Job(name="live", job_type="PACKAGE_UPDATE", target_servers={},
                        status=JobStatus.RUNNING, created_at=now))
    await db_session.commit()

    resp = await client.get("/api/v1/dashboard/trends", params={"range": "7d"})
    assert resp.status_code == 200
    today = resp.json()["jobs"][-1]
    assert today["successful"] == 1
    assert today["failed"] == 1
    assert today["running"] == 1


@pytest.mark.asyncio
async def test_trends_alerts_bucketed_by_triggered_and_resolved(
    client: AsyncClient, db_session
):
    now = datetime.now(timezone.utc)
    db_session.add(Alert(title="new-alert", severity="HIGH", status="ACTIVE", triggered_at=now))
    db_session.add(
        Alert(title="closed-alert", severity="LOW", status="RESOLVED",
              triggered_at=now - timedelta(days=1), resolved_at=now)
    )
    await db_session.commit()

    resp = await client.get("/api/v1/dashboard/trends", params={"range": "7d"})
    assert resp.status_code == 200
    today = resp.json()["alerts"][-1]
    assert today["created"] == 1
    assert today["resolved"] == 1


@pytest.mark.asyncio
async def test_trends_rejects_invalid_range(client: AsyncClient):
    resp = await client.get("/api/v1/dashboard/trends", params={"range": "3w"})
    assert resp.status_code == 422
