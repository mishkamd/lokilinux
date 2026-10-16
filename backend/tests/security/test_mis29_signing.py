"""MIS-29 checklist 3 and 4: a privileged job that cannot be signed must not be
dispatched unsigned, and approve_job must actually issue the approval claim.

Fixtures (db_session, fake_cache) come from tests/conftest.py.
"""

import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

# Same-directory helpers from the CR-03 suite: real CA + agent cert, and the
# stub gRPC context (auth_context/abort) the identity gate reads.
from test_security_p0 import _issue_agent_cert, _make_ca, _StubContext

from lokilinux.api.grpc.agent_service import AgentServicer
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.approval import ApprovalClaim
from lokilinux.models.job import JobResult
from lokilinux.services import job_envelope, job_service
from lokilinux.services.job_service import JobService


class _BrokenSigner:
    def sign(self, **kwargs):
        raise RuntimeError("signing backend unreachable")


class _WorkingSigner:
    def sign(self, **kwargs):
        return {"signature": "fake"}


def test_unsignable_privileged_job_raises_instead_of_going_unsigned(monkeypatch):
    """A privileged job for a new-enough agent that cannot be signed must raise
    EnvelopeSigningError. Returning the params as-is dispatches an unsigned
    privileged job, which is exactly what signed dispatch exists to prevent."""
    monkeypatch.setattr(job_envelope, "_get_signer", lambda: _BrokenSigner())
    job = SimpleNamespace(id="j-1", job_type="SERVICE", agent_id="a-1", tenant_id="", policy_id="")

    with pytest.raises(Exception) as ei:
        job_envelope.maybe_attach_envelope(
            job, {"service_name": "nginx"}, "9.9.9", agent_id="wire-1"
        )

    assert isinstance(ei.value, job_envelope.EnvelopeSigningError)


class _FakeApprovalSigner:
    def __init__(self):
        self.calls = []

    def sign_approval_claim(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "approval_id": uuid.uuid4().hex,
            "job_id": kwargs["job_id"],
            "target_agent_id": kwargs["target_agent_id"],
            "expires_at": int(datetime.now(timezone.utc).timestamp()) + 300,
            "signature": "fake",
        }


@pytest.mark.asyncio
async def test_approve_job_issues_claim_bound_to_wire_agent_id(db_session, fake_cache, monkeypatch):
    """approve_job must write an ApprovalClaim row and expose it on the job.
    The claim targets the agent's wire identity (Agent.agent_id), because the
    agent checks claim.target_agent_id against its own agent_id, not the PK."""
    signer = _FakeApprovalSigner()
    monkeypatch.setattr(job_service, "_get_job_signer", lambda: signer)

    agent = Agent(
        agent_id=f"wire-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(agent)
    await db_session.flush()

    svc = JobService(db_session, fake_cache)
    job = await svc.create_job(
        name="approval gated",
        job_type="SERVICE",
        target_servers={"agent_ids": [str(agent.id)]},
        parameters={"service_name": "nginx"},
        requires_approval=True,
    )

    approved = await svc.approve_job(job.id, approved_by=None)

    claims = (
        await db_session.execute(select(ApprovalClaim).where(ApprovalClaim.job_id == job.id))
    ).scalars().all()
    assert len(claims) == 1, "approve_job must persist exactly one ApprovalClaim row"
    assert approved.approval_claim_json is not None
    assert signer.calls[0]["target_agent_id"] == agent.agent_id
    assert claims[0].expires_at > datetime.now(timezone.utc) + timedelta(seconds=60)


@pytest.mark.asyncio
async def test_heartbeat_holds_unsignable_privileged_job_and_dispatches_the_rest(
    db_session, fake_cache, fake_nats, tmp_path, monkeypatch
):
    """Checklist 3, dispatch side: a privileged job that cannot be signed is left
    out of this heartbeat's pending_jobs and stays PENDING for the next one, while
    a non-privileged job is still dispatched."""
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

    async def heartbeat() -> dict:
        async def req_iter():
            # 0.40.0: signed-jobs capable, but below the FIM-scope gate (0.41.0), so
            # the heartbeat does not also sign FIM config with the policy key on disk.
            yield SimpleNamespace(agent_id=wire_id, agent_version="0.40.0")

        messages = [m async for m in servicer.HeartbeatStream(req_iter(), _StubContext(pem=pem))]
        return {j["job_id"]: j["parameters"] for m in messages for j in m.get("pending_jobs", [])}

    first = await heartbeat()
    assert str(held.id) not in first, "unsignable privileged job must not go out unsigned"
    assert str(sent.id) in first
    held_result = (
        await db_session.execute(
            select(JobResult).where(JobResult.job_id == held.id, JobResult.agent_id == agent.id)
        )
    ).scalar_one()
    assert held_result.status == "PENDING", "held job must be re-selectable on the next heartbeat"

    monkeypatch.setattr(job_envelope, "_get_signer", lambda: _WorkingSigner())
    second = await heartbeat()
    assert "_envelope" in second[str(held.id)], "retry with a healthy signer dispatches it signed"
