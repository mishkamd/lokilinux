"""Four-eyes on approvals: the requester cannot approve their own job, baseline version
or compliance exception (MIS-179). Nanoid ids are the case the UUID columns miss."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.baseline import BaselineVersion
from lokilinux.models.compliance_exception import ComplianceException
from lokilinux.models.playbook import Playbook
from lokilinux.models.policy import Policy
from lokilinux.services.baseline_service import BaselineService
from lokilinux.services.compliance_exception_service import ExceptionService
from lokilinux.services.job_service import JobService
from lokilinux.services.playbook_service import PlaybookService
from lokilinux.services.policy_service import run_policy


@pytest.mark.asyncio
async def test_job_requester_cannot_approve_own_job(db_session, fake_cache, fake_nats):
    agent = Agent(
        agent_id=f"wire-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(agent)
    await db_session.flush()
    svc = JobService(db_session, fake_cache, fake_nats)
    job = await svc.create_job(
        name="four-eyes",
        job_type="SERVICE",
        target_servers={"agent_ids": [str(agent.id)]},
        parameters={"service_name": "nginx"},
        requires_approval=True,
        created_by_actor="nanoid-requester",
     actor_role="ADMIN",)

    with pytest.raises(PermissionError, match="cannot approve their own"):
        await svc.approve_job(job.id, None, approver_actor="nanoid-requester")

    await svc.approve_job(job.id, None, approver_actor="nanoid-approver")
    assert job.approved_at is not None


@pytest.mark.asyncio
async def test_baseline_author_cannot_approve_own_version(db_session, fake_nats):
    svc = BaselineService(db_session, fake_nats)
    baseline = await svc.create_baseline(
        name="four-eyes",
        scope_type="GLOBAL",
        scope_selector={},
        expected_state={"k": "v"},
        created_by_actor="nanoid-author",
    )
    version = (
        await db_session.execute(
            select(BaselineVersion).where(BaselineVersion.baseline_id == baseline.id)
        )
    ).scalar_one()
    await svc.submit(version.id, {"id": "nanoid-author"})

    with pytest.raises(HTTPException) as err:
        await svc.approve(version.id, {"id": "nanoid-author"})
    assert err.value.status_code == 403


@pytest.mark.asyncio
async def test_exception_requester_cannot_approve_own_exception(db_session):
    # Transient object: the four-eyes check runs before any DB access.
    exc = ComplianceException(
        status="PENDING",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        requested_by_actor="nanoid-requester",
    )

    with pytest.raises(HTTPException) as err:
        await ExceptionService(db_session).approve(exc, {"id": "nanoid-requester"}, None)
    assert err.value.status_code == 403


@pytest.mark.asyncio
async def test_manual_policy_run_records_requester(db_session, fake_cache):
    agent = Agent(agent_id=f"wire-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE,
                  hostname=f"host-{uuid.uuid4().hex[:8]}")
    db_session.add(agent)
    await db_session.flush()  # agent.id is server-generated; the policy needs it
    policy = Policy(
        name="four-eyes", rules={}, target_servers={"agent_ids": [str(agent.id)]},
        actions=[{"type": "PACKAGE_UPDATE", "params": {"package_names": ["curl"]}}],
        execution={"requires_approval": True}, created_by=uuid.uuid4(),
    )
    db_session.add(policy)
    await db_session.commit()

    job_ids, _ = await run_policy(
        db_session, policy, fake_cache, triggered_by="manual", created_by_actor="nanoid-operator"
    , actor_role="ADMIN")

    with pytest.raises(PermissionError, match="cannot approve their own"):
        await JobService(db_session, fake_cache).approve_job(
            job_ids[0], None, approver_actor="nanoid-operator"
        )


@pytest.mark.asyncio
async def test_playbook_run_records_requester(db_session, fake_cache, fake_storage, fake_nats, monkeypatch):
    async def agents_ok(self, agent_ids):  # capability check is not under test here
        return None

    monkeypatch.setattr(PlaybookService, "_assert_agents_can_run_ansible", agents_ok)
    agent = Agent(agent_id=f"wire-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE,
                  hostname=f"host-{uuid.uuid4().hex[:8]}")
    playbook = Playbook(name="four-eyes", content="- hosts: all\n  tasks: []\n")
    db_session.add_all([agent, playbook])
    await db_session.commit()

    job = await PlaybookService(db_session, fake_cache, fake_storage, fake_nats).execute_playbook(
        playbook.id, agent_ids=[agent.id], created_by_actor="nanoid-operator",
     actor_role="ADMIN",)

    with pytest.raises(PermissionError, match="cannot approve their own"):
        await JobService(db_session, fake_cache, fake_nats).approve_job(
            job.id, None, approver_actor="nanoid-operator"
        )
