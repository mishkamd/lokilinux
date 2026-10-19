"""MIS-29 root cause of the held-job revert: a privileged job that fails envelope
signing must never be marked RUNNING in the first place, so nothing has to put
it back to PENDING. Only jobs actually dispatched in a heartbeat go RUNNING.

Fixtures (db_session, fake_cache, fake_nats) come from tests/conftest.py.
"""

import contextlib
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

# Same-directory helpers: real CA + agent cert and the stub gRPC context (CR-03 suite),
# and the broken signer from the checklist 3/4 suite.
from test_mis29_signing import _BrokenSigner
from test_security_p0 import _issue_agent_cert, _make_ca, _StubContext

from lokilinux.api.grpc.agent_service import AgentServicer
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.job import Job, JobResult, JobStatus
from lokilinux.services import job_envelope
from lokilinux.services.agent_service import AgentService
from lokilinux.services.job_service import JobService


async def _setup(db_session, fake_cache, fake_nats, tmp_path, monkeypatch):
    """One agent with a privileged SERVICE job (signing broken, so it is held) and a
    non-privileged INVENTORY_SCAN job (dispatched). Returns (servicer, wire_id, pem, held, sent)."""
    _, ca_key, ca_cert = _make_ca(tmp_path)
    wire_id = str(uuid.uuid4())
    pem = _issue_agent_cert(ca_key, ca_cert, wire_id)
    agent = Agent(
        agent_id=wire_id, status=AgentStatus.ACTIVE, hostname=f"host-{uuid.uuid4().hex[:8]}"
    )
    db_session.add(agent)
    await db_session.flush()

    svc = JobService(db_session, fake_cache, fake_nats)
    held = await svc.create_job(
        name="held", job_type="SERVICE",
        target_servers={"agent_ids": [str(agent.id)]},
        parameters={"service_name": "nginx"},
    )
    sent = await svc.create_job(
        name="sent", job_type="INVENTORY_SCAN",
        target_servers={"agent_ids": [str(agent.id)]},
    )
    monkeypatch.setattr(job_envelope, "_get_signer", lambda: _BrokenSigner())

    @contextlib.asynccontextmanager
    async def session_factory():
        yield db_session

    servicer = AgentServicer(db_factory=session_factory, cache=fake_cache, nats=fake_nats)
    return servicer, wire_id, pem, held, sent


async def _heartbeat(servicer, wire_id, pem) -> set[str]:
    async def req_iter():
        # 0.40.0: signed-jobs capable, below the FIM-scope gate (0.41.0).
        yield SimpleNamespace(agent_id=wire_id, agent_version="0.40.0")

    messages = [m async for m in servicer.HeartbeatStream(req_iter(), _StubContext(pem=pem))]
    return {j["job_id"] for m in messages for j in m.get("pending_jobs", [])}


async def _state(db_session, job) -> tuple[JobResult, Job]:
    # populate_existing: the bulk UPDATEs must be re-read, not served from the identity map.
    result = (
        await db_session.execute(
            select(JobResult)
            .where(JobResult.job_id == job.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    refreshed = await db_session.get(Job, job.id, populate_existing=True)
    return result, refreshed


@pytest.mark.asyncio
async def test_held_job_is_never_marked_running(
    db_session, fake_cache, fake_nats, tmp_path, monkeypatch
):
    """A job held for a signing failure stays PENDING and unstarted at the JobResult
    and the Job level. Today the Job row is left RUNNING: the revert only undoes the
    JobResult, so the held job looks in progress with nothing running it."""
    servicer, wire_id, pem, held, sent = await _setup(
        db_session, fake_cache, fake_nats, tmp_path, monkeypatch
    )

    dispatched = await _heartbeat(servicer, wire_id, pem)

    assert str(held.id) not in dispatched
    result, job = await _state(db_session, held)
    assert result.status == "PENDING"
    assert result.started_at is None
    assert job.status == JobStatus.QUEUED
    assert job.started_at is None


@pytest.mark.asyncio
async def test_dispatched_job_is_marked_running_on_heartbeat(
    db_session, fake_cache, fake_nats, tmp_path, monkeypatch
):
    """Guard: a job that goes out in the heartbeat is RUNNING at both levels."""
    servicer, wire_id, pem, held, sent = await _setup(
        db_session, fake_cache, fake_nats, tmp_path, monkeypatch
    )

    dispatched = await _heartbeat(servicer, wire_id, pem)

    assert str(sent.id) in dispatched
    result, job = await _state(db_session, sent)
    assert result.status == "RUNNING"
    assert result.started_at is not None
    assert job.status == JobStatus.RUNNING
    assert job.started_at is not None


@pytest.mark.asyncio
async def test_get_pending_jobs_only_selects(db_session, fake_cache):
    """get_pending_jobs is a read. Marking RUNNING belongs to the caller, once it knows
    the job is going out on this heartbeat."""
    agent = Agent(
        agent_id=f"agent-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE, hostname="web-01"
    )
    db_session.add(agent)
    await db_session.flush()
    job = Job(
        name="patch", job_type="PACKAGE_UPDATE",
        target_servers={"agent_ids": [agent.agent_id]}, status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(JobResult(job_id=job.id, agent_id=agent.id, status="PENDING"))
    await db_session.flush()

    pending = await AgentService(db_session, fake_cache).get_pending_jobs(agent.id)

    assert [j.id for j in pending] == [job.id]
    result, refreshed = await _state(db_session, job)
    assert result.status == "PENDING"
    assert result.started_at is None
    assert refreshed.status == JobStatus.QUEUED


@pytest.mark.asyncio
async def test_a_job_is_claimed_by_one_heartbeat_only(db_session, fake_cache):
    """Two heartbeats can select the same PENDING job. Only the one whose UPDATE moves
    it to RUNNING may send it; the other must get nothing back, or the job is sent twice."""
    agent = Agent(
        agent_id=f"agent-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE, hostname="web-02"
    )
    db_session.add(agent)
    await db_session.flush()
    job = Job(
        name="patch", job_type="PACKAGE_UPDATE",
        target_servers={"agent_ids": [agent.agent_id]}, status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(JobResult(job_id=job.id, agent_id=agent.id, status="PENDING"))
    await db_session.flush()

    svc = AgentService(db_session, fake_cache)
    first = await svc.mark_dispatched(agent.id, [job])
    second = await svc.mark_dispatched(agent.id, [job])

    assert [j.id for j in first] == [job.id]
    assert second == []
