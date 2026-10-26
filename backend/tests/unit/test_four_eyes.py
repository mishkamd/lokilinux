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
from lokilinux.services.baseline_service import BaselineService
from lokilinux.services.compliance_exception_service import ExceptionService
from lokilinux.services.job_service import JobService


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
    )

    with pytest.raises(ValueError, match="cannot approve their own"):
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
