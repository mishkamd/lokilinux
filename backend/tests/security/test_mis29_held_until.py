"""MIS-29 hold window: a job held back for a signing failure is skipped by
get_pending_jobs until JobResult.held_until has passed, so held jobs stop filling the
pending window and stop being re-signed on every heartbeat.

Fixtures (db_session, fake_cache, fake_nats) come from tests/conftest.py.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

# Same-directory helpers: the held-job heartbeat driver and the agent/job setups.
from test_mis29_root_held_jobs import _heartbeat, _setup, _state
from test_mis29_starvation_and_signer_retry import _agent_with_jobs

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.job import Job, JobResult, JobStatus
from lokilinux.services.agent_service import AgentService


async def _agent_for(db_session, wire_id: str) -> Agent:
    return (
        await db_session.execute(select(Agent).where(Agent.agent_id == wire_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_held_job_is_skipped_while_its_hold_is_live(
    db_session, fake_cache, fake_nats, tmp_path, monkeypatch
):
    """After a heartbeat holds a privileged job, get_pending_jobs must not return it
    while held_until is in the future. The non-privileged job still goes out."""
    servicer, wire_id, pem, held, sent = await _setup(
        db_session, fake_cache, fake_nats, tmp_path, monkeypatch
    )

    dispatched = await _heartbeat(servicer, wire_id, pem)

    assert str(sent.id) in dispatched
    agent = await _agent_for(db_session, wire_id)
    pending = await AgentService(db_session, fake_cache).get_pending_jobs(agent.id)
    assert str(held.id) not in [str(j.id) for j in pending]
    result, _ = await _state(db_session, held)
    assert result.held_until is not None
    assert result.held_until > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_held_job_is_selected_again_once_the_hold_expires(
    db_session, fake_cache, fake_nats, tmp_path, monkeypatch
):
    """Guard: once held_until has passed, the held job is pending again and is selected.
    Simulated by moving held_until into the past directly in the DB."""
    servicer, wire_id, pem, held, sent = await _setup(
        db_session, fake_cache, fake_nats, tmp_path, monkeypatch
    )
    await _heartbeat(servicer, wire_id, pem)
    agent = await _agent_for(db_session, wire_id)
    await db_session.execute(
        update(JobResult)
        .where(JobResult.job_id == held.id, JobResult.agent_id == agent.id)
        .values(held_until=datetime.now(timezone.utc) - timedelta(seconds=1))
    )

    pending = await AgentService(db_session, fake_cache).get_pending_jobs(agent.id)

    assert str(held.id) in [str(j.id) for j in pending]


@pytest.mark.asyncio
async def test_more_than_thirty_held_jobs_do_not_starve_a_non_privileged_job(
    db_session, fake_cache, fake_nats, tmp_path, monkeypatch
):
    """31 privileged jobs held for a signing failure must not use up the heartbeat's
    rounds before the non-privileged job queued behind them is reached."""
    servicer, wire_id, pem, held, sent = await _agent_with_jobs(
        db_session, fake_cache, fake_nats, tmp_path, monkeypatch, held=31, sent=1
    )

    dispatched = await _heartbeat(servicer, wire_id, pem)

    assert str(sent[0].id) in dispatched
    for job in held:
        assert str(job.id) not in dispatched


@pytest.mark.asyncio
async def test_dispatch_clears_an_expired_hold(db_session, fake_cache):
    """mark_dispatched claims a job and clears its hold, so the hold never outlives
    the send."""
    agent = Agent(
        agent_id=f"agent-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE, hostname="web-03"
    )
    db_session.add(agent)
    await db_session.flush()
    job = Job(
        name="patch", job_type="PACKAGE_UPDATE",
        target_servers={"agent_ids": [agent.agent_id]}, status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(JobResult(
        job_id=job.id, agent_id=agent.id, status="PENDING",
        held_until=datetime.now(timezone.utc) - timedelta(seconds=1),
    ))
    await db_session.flush()

    await AgentService(db_session, fake_cache).mark_dispatched(agent.id, [job])

    result, _ = await _state(db_session, job)
    assert result.status == "RUNNING"
    assert result.held_until is None
