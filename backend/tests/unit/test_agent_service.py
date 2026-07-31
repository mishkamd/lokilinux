"""
Unit tests for AgentService.update_heartbeat / get_pending_jobs / mark_inactive.

Regression coverage: a heartbeat carrying non-empty fqdn/agent_version must
persist them (this is the exact field pair that showed up blank on the
Overview tab — see docs/AGENT.md#troubleshooting).
"""

import uuid

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentHealth, AgentStatus
from lokilinux.models.cve import CVE, AgentVulnerability, Package
from lokilinux.models.job import Job, JobResult, JobStatus
from lokilinux.services.agent_service import AgentService


async def _make_agent(db_session, **overrides) -> Agent:
    agent = Agent(
        agent_id=overrides.pop("agent_id", str(uuid.uuid4())),
        status=overrides.pop("status", AgentStatus.PENDING),
        hostname=overrides.pop("hostname", "web-01"),
        **overrides,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_update_heartbeat_activates_agent_and_sets_ip(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-abc")
    svc = AgentService(db_session, fake_cache)

    updated = await svc.update_heartbeat("agent-abc", {"ip_address": "10.0.0.5"})

    assert updated.status == AgentStatus.ACTIVE
    assert updated.last_heartbeat_ip == "10.0.0.5"
    assert updated.last_heartbeat is not None


@pytest.mark.asyncio
async def test_update_heartbeat_persists_fqdn_and_agent_version(db_session, fake_cache):
    """Regression: Overview tab showed FQDN/Agent Version as '—' — verify the
    heartbeat write path stores both when the agent reports them."""
    agent = await _make_agent(db_session, agent_id="agent-fqdn")
    svc = AgentService(db_session, fake_cache)

    updated = await svc.update_heartbeat(
        "agent-fqdn",
        {
            "system_status": {"fqdn": "web-01.internal.example.com", "hostname": "web-01"},
            "agent_version": "1.4.2",
        },
    )

    assert updated.fqdn == "web-01.internal.example.com"
    assert updated.agent_version == "1.4.2"


@pytest.mark.asyncio
async def test_update_heartbeat_ignores_empty_system_status_values(db_session, fake_cache):
    """Falsy values (empty string) must not clobber a previously known field."""
    agent = await _make_agent(db_session, agent_id="agent-keep", fqdn="already-set.example.com")
    svc = AgentService(db_session, fake_cache)

    updated = await svc.update_heartbeat(
        "agent-keep",
        {"system_status": {"fqdn": ""}},
    )

    assert updated.fqdn == "already-set.example.com"


@pytest.mark.asyncio
async def test_update_heartbeat_unknown_agent_raises(db_session, fake_cache):
    svc = AgentService(db_session, fake_cache)
    with pytest.raises(ValueError):
        await svc.update_heartbeat("does-not-exist", {})


@pytest.mark.asyncio
async def test_update_heartbeat_syncs_recent_logs_shape(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-logs")
    svc = AgentService(db_session, fake_cache)

    updated = await svc.update_heartbeat(
        "agent-logs",
        {
            "recent_logs": ["line one", "line two"],
            "log_connections": 3,
            "log_informative": 1,
            "log_critical": 0,
        },
    )

    assert updated.recent_logs == {
        "lines": ["line one", "line two"],
        "connections": 3,
        "informative": 1,
        "critical": 0,
    }


@pytest.mark.asyncio
async def test_update_heartbeat_upserts_packages(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-pkg")
    svc = AgentService(db_session, fake_cache)

    await svc.update_heartbeat(
        "agent-pkg",
        {"packages": [{"name": "curl", "version": "8.1.0", "architecture": "amd64"}]},
    )
    rows = (await db_session.execute(select(Package).where(Package.agent_id == agent.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "curl" and rows[0].version == "8.1.0"

    # second heartbeat with an update flag flips the existing row instead of duplicating it
    await svc.update_heartbeat(
        "agent-pkg",
        {"packages": [{"name": "curl", "version": "8.1.0", "update_available": True, "latest_version": "8.2.0"}]},
    )
    rows = (
        await db_session.execute(
            select(Package).where(Package.agent_id == agent.id).execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_update_available is True
    assert rows[0].latest_version == "8.2.0"


@pytest.mark.asyncio
async def test_update_heartbeat_upserts_vulnerabilities(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-vuln")
    svc = AgentService(db_session, fake_cache)

    await svc.update_heartbeat(
        "agent-vuln",
        {"vulnerabilities": [
            {"cve_id": "CVE-2026-1", "package_name": "openssl", "installed_version": "1.0", "severity": "HIGH"},
        ]},
    )

    cve = (await db_session.execute(select(CVE).where(CVE.cve_id == "CVE-2026-1"))).scalar_one()
    assert cve.cvss_v3_severity == "HIGH"

    rows = (
        await db_session.execute(select(AgentVulnerability).where(AgentVulnerability.agent_id == agent.id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].package_name == "openssl" and rows[0].is_remediated is False

    # Fixed now (no longer reported) — reconcile marks it remediated, doesn't delete it.
    await svc.update_heartbeat("agent-vuln", {"vulnerabilities": []})

    rows = (
        await db_session.execute(
            select(AgentVulnerability)
            .where(AgentVulnerability.agent_id == agent.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_remediated is True
    assert rows[0].remediation_date is not None


@pytest.mark.asyncio
async def test_update_heartbeat_invalidates_cache(db_session, fake_cache):
    """Regression: GET /servers/{pk} caches under agent:{PK}:detail, but
    update_heartbeat used to invalidate agent:{agent_id string}:* — a
    different key that's never populated, so the Overview tab stayed stale
    forever after every heartbeat."""
    agent = await _make_agent(db_session, agent_id="agent-cache")
    fake_cache._store[f"agent:{agent.id}:detail"] = {"stale": True}
    svc = AgentService(db_session, fake_cache)

    await svc.update_heartbeat("agent-cache", {})

    assert f"agent:{agent.id}:detail" not in fake_cache._store


@pytest.mark.asyncio
async def test_get_pending_jobs_returns_only_pending_results(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-jobs")
    job = Job(name="patch", job_type="PACKAGE_UPDATE", target_servers={"agent_ids": [agent.agent_id]}, status=JobStatus.QUEUED)
    db_session.add(job)
    await db_session.flush()

    db_session.add(JobResult(job_id=job.id, agent_id=agent.id, status="PENDING"))
    await db_session.flush()

    svc = AgentService(db_session, fake_cache)
    pending = await svc.get_pending_jobs(agent.id)

    assert len(pending) == 1
    assert pending[0].id == job.id


@pytest.mark.asyncio
async def test_mark_inactive_sets_status(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-stale", status=AgentStatus.ACTIVE)
    svc = AgentService(db_session, fake_cache)

    await svc.mark_inactive(agent.id)

    refreshed = (await db_session.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
    assert refreshed.status == AgentStatus.INACTIVE


@pytest.mark.asyncio
async def test_update_heartbeat_records_health_snapshot(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-health")
    svc = AgentService(db_session, fake_cache)

    await svc.update_heartbeat(
        "agent-health",
        {"health": {"cpu_usage": 12.5, "memory_usage": 95.0, "disk_usage": 91.0}},
    )

    rows = (await db_session.execute(select(AgentHealth).where(AgentHealth.agent_id == agent.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].memory_usage == 95.0
    assert rows[0].is_memory_critical is True
    assert rows[0].is_disk_full is True


@pytest.mark.asyncio
async def test_update_heartbeat_applies_job_results(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-jobresult")
    job = Job(name="patch", job_type="PACKAGE_UPDATE", target_servers={"agent_ids": ["agent-jobresult"]}, status=JobStatus.QUEUED)
    db_session.add(job)
    await db_session.flush()
    result_row = JobResult(job_id=job.id, agent_id=agent.id, status="PENDING")
    db_session.add(result_row)
    await db_session.flush()

    svc = AgentService(db_session, fake_cache)
    await svc.update_heartbeat(
        "agent-jobresult",
        {"job_results": [{"job_id": str(job.id), "state": 2, "exit_code": 0, "output": "done"}]},
    )

    refreshed = (await db_session.execute(select(JobResult).where(JobResult.id == result_row.id))).scalar_one()
    assert refreshed.status == "COMPLETED"
    assert refreshed.exit_code == 0
    assert refreshed.stdout == "done"
    assert refreshed.completed_at is not None


@pytest.mark.asyncio
async def test_two_agent_job_partial_completion_sets_running_then_terminal(db_session, fake_cache):
    """Fan-out job to 2 agents: first completion -> Job.status RUNNING with
    started_at set; second completion -> Job.status COMPLETED."""
    agent1 = await _make_agent(db_session, agent_id="agent-multi-1")
    agent2 = await _make_agent(db_session, agent_id="agent-multi-2")
    job = Job(
        name="multi-agent patch",
        job_type="PACKAGE_UPDATE",
        target_servers={"agent_ids": [str(agent1.id), str(agent2.id)]},
        status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add_all([
        JobResult(job_id=job.id, agent_id=agent1.id, status="PENDING"),
        JobResult(job_id=job.id, agent_id=agent2.id, status="PENDING"),
    ])
    await db_session.flush()

    svc = AgentService(db_session, fake_cache)

    # agent1 finishes, agent2 hasn't reported yet
    await svc.update_heartbeat(
        "agent-multi-1",
        {"job_results": [{"job_id": str(job.id), "state": 2, "exit_code": 0, "output": "ok"}]},
    )
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == JobStatus.RUNNING
    assert refreshed.started_at is not None
    assert refreshed.completed_at is None

    # agent2 finishes too -> job fully terminal
    await svc.update_heartbeat(
        "agent-multi-2",
        {"job_results": [{"job_id": str(job.id), "state": 2, "exit_code": 0, "output": "ok"}]},
    )
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == JobStatus.COMPLETED
    assert refreshed.completed_at is not None


@pytest.mark.asyncio
async def test_two_agent_job_any_failure_marks_job_failed(db_session, fake_cache):
    agent1 = await _make_agent(db_session, agent_id="agent-fail-1")
    agent2 = await _make_agent(db_session, agent_id="agent-fail-2")
    job = Job(
        name="multi-agent patch",
        job_type="PACKAGE_UPDATE",
        target_servers={"agent_ids": [str(agent1.id), str(agent2.id)]},
        status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add_all([
        JobResult(job_id=job.id, agent_id=agent1.id, status="PENDING"),
        JobResult(job_id=job.id, agent_id=agent2.id, status="PENDING"),
    ])
    await db_session.flush()

    svc = AgentService(db_session, fake_cache)
    await svc.update_heartbeat(
        "agent-fail-1",
        {"job_results": [{"job_id": str(job.id), "state": 3, "exit_code": 1, "error_message": "boom"}]},
    )
    await svc.update_heartbeat(
        "agent-fail-2",
        {"job_results": [{"job_id": str(job.id), "state": 2, "exit_code": 0}]},
    )
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == JobStatus.FAILED


@pytest.mark.asyncio
async def test_update_heartbeat_skips_package_sync_when_checksum_unchanged(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-checksum", last_packages_checksum="abc123")
    svc = AgentService(db_session, fake_cache)

    await svc.update_heartbeat(
        "agent-checksum",
        {
            "packages": [{"name": "curl", "version": "8.1.0"}],
            "packages_checksum": "abc123",
        },
    )

    rows = (await db_session.execute(select(Package).where(Package.agent_id == agent.id))).scalars().all()
    assert rows == []  # upsert skipped entirely — checksum matched


@pytest.mark.asyncio
async def test_update_heartbeat_syncs_and_stores_checksum_when_changed(db_session, fake_cache):
    agent = await _make_agent(db_session, agent_id="agent-checksum2", last_packages_checksum="old")
    svc = AgentService(db_session, fake_cache)

    await svc.update_heartbeat(
        "agent-checksum2",
        {
            "packages": [{"name": "curl", "version": "8.1.0"}],
            "packages_checksum": "new",
        },
    )

    rows = (await db_session.execute(select(Package).where(Package.agent_id == agent.id))).scalars().all()
    assert len(rows) == 1

    refreshed = (await db_session.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
    assert refreshed.last_packages_checksum == "new"
