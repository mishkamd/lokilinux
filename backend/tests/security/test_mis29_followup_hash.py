"""MIS-29 follow-up: an approval claim hashes the parameters the agent receives.

COMPLIANCE_REMEDIATE jobs send each agent only its own actions. The claim's job_hash
is checked agent-side against exactly what that agent got, so approve_job must hash
the same per-agent view. Hashing the full fleet-wide parameters makes every claim
fail verification.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.services import job_service
from lokilinux.services.job_service import JobService


class _RecordingSigner:
    """Stands in for the job signer so the payload each claim covers can be read back."""

    def __init__(self):
        self.payloads = {}

    def sign_approval_claim(self, *, job_id, target_agent_id, payload, **_):
        self.payloads[target_agent_id] = payload
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        return {"job_id": job_id, "expires_at": int(expires.timestamp())}


async def _make_agent(db_session) -> Agent:
    agent = Agent(
        agent_id=f"wire-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_compliance_remediate_claim_covers_each_agents_own_view(
    db_session, fake_cache, fake_nats, monkeypatch
):
    signer = _RecordingSigner()
    monkeypatch.setattr(job_service, "_get_job_signer", lambda: signer)
    first, second = await _make_agent(db_session), await _make_agent(db_session)

    svc = JobService(db_session, fake_cache, fake_nats)
    job = await svc.create_job(
        name="remediate per agent",
        job_type="COMPLIANCE_REMEDIATE",
        target_servers={"agent_ids": [str(first.id), str(second.id)]},
        parameters={
            "remediation_plan_id": "plan-1",
            "operation": "apply",
            "actions": {
                str(first.id): [{"rule": "r1"}],
                str(second.id): [{"rule": "r2"}],
            },
        },
        requires_approval=True,
     actor_role="ADMIN",)
    await svc.approve_job(job.id, approved_by=None)

    for agent in (first, second):
        assert signer.payloads[agent.agent_id] == job_service.parameters_for_agent(job, agent.id)
    assert signer.payloads[first.agent_id] != signer.payloads[second.agent_id]
