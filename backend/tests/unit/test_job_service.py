"""Unit tests for JobService.complete_job status aggregation."""

import uuid

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.job import Job, JobResult, JobStatus
from lokilinux.models.plugin import Plugin, PluginInstallation, PluginStatus
from lokilinux.services.job_service import JobService


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
async def test_complete_job_partial_then_full_completion(db_session, fake_cache):
    a1 = await _make_agent(db_session, agent_id="svc-agent-1")
    a2 = await _make_agent(db_session, agent_id="svc-agent-2")
    job = Job(
        name="j",
        job_type="PACKAGE_UPDATE",
        target_servers={"agent_ids": [str(a1.id), str(a2.id)]},
        status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add_all([
        JobResult(job_id=job.id, agent_id=a1.id, status="PENDING"),
        JobResult(job_id=job.id, agent_id=a2.id, status="PENDING"),
    ])
    await db_session.flush()

    svc = JobService(db_session, fake_cache)
    await svc.complete_job(job.id, a1.id, exit_code=0, stdout="", stderr="", duration_ms=1000)

    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == JobStatus.RUNNING
    assert refreshed.started_at is not None
    assert refreshed.completed_at is None

    await svc.complete_job(job.id, a2.id, exit_code=1, stdout="", stderr="err", duration_ms=500)
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == JobStatus.FAILED
    assert refreshed.completed_at is not None


@pytest.mark.asyncio
async def test_plugin_install_job_syncs_plugin_state(db_session, fake_cache):
    a1 = await _make_agent(db_session, agent_id="plug-agent-1")
    a2 = await _make_agent(db_session, agent_id="plug-agent-2")
    plugin = Plugin(
        name="demo-plugin",
        version="1.0.0",
        plugin_type="agent",
        installation_status=PluginStatus.INSTALLING,
    )
    db_session.add(plugin)
    await db_session.flush()
    db_session.add_all([
        PluginInstallation(plugin_id=plugin.id, agent_id=a1.id, status="PENDING_INSTALL"),
        PluginInstallation(plugin_id=plugin.id, agent_id=a2.id, status="PENDING_INSTALL"),
    ])
    job = Job(
        name="Install plugin demo-plugin v1.0.0",
        job_type="PLUGIN_INSTALL",
        target_servers={"agent_ids": [str(a1.id), str(a2.id)]},
        parameters={"plugin_id": str(plugin.id)},
        status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add_all([
        JobResult(job_id=job.id, agent_id=a1.id, status="PENDING"),
        JobResult(job_id=job.id, agent_id=a2.id, status="PENDING"),
    ])
    await db_session.flush()

    svc = JobService(db_session, fake_cache)

    # first agent succeeds — plugin still INSTALLING, its installation done
    await svc.complete_job(job.id, a1.id, exit_code=0, stdout="ok", stderr="", duration_ms=100)
    assert plugin.installation_status == PluginStatus.INSTALLING
    inst1 = (await db_session.execute(
        select(PluginInstallation).where(PluginInstallation.agent_id == a1.id)
    )).scalar_one()
    assert inst1.status == "INSTALLED"

    # second agent fails — plugin flips to INSTALLING_FAILED with error detail
    await svc.complete_job(job.id, a2.id, exit_code=1, stdout="", stderr="checksum mismatch", duration_ms=50)
    assert plugin.installation_status == PluginStatus.INSTALLING_FAILED
    inst2 = (await db_session.execute(
        select(PluginInstallation).where(PluginInstallation.agent_id == a2.id)
    )).scalar_one()
    assert inst2.status == "ERROR"
    assert "checksum mismatch" in (inst2.error_message or "")
