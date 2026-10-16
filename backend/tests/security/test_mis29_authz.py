"""MIS-29 authorization regressions: no self-approval of remediation plans,
maintenance toggle and job cancel are role-gated (checklist points 5-7).

Removing any guard here must fail CI.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.audit import AuditLog
from lokilinux.models.job import Job, JobStatus
from lokilinux.schemas.remediation import RemediationActionCreate
from lokilinux.services.job_service import JobService
from lokilinux.services.remediation_service import RemediationService


async def _make_agent(db_session) -> Agent:
    agent = Agent(
        agent_id=str(uuid.uuid4()),
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


# ── Point 5 · remediation plans: no self-approval ─────────────────────────────


@pytest.mark.asyncio
async def test_plan_creator_cannot_approve_own_plan(
    client: AsyncClient, db_session, current_user, fake_cache, fake_nats
):
    creator = str(uuid.uuid4())
    agent = await _make_agent(db_session)
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))
    plan = await svc.create_plan(
        name="self-approve",
        trigger_type="MANUAL",
        actions=[
            RemediationActionCreate(agent_id=agent.id, provider="shell", rendered_body="echo fix"),
        ],
        created_by=uuid.UUID(creator),
    )
    await svc.submit(plan.id, {"id": creator})
    await db_session.commit()

    current_user.update(id=creator, role="OPERATOR")
    resp = await client.post(f"/api/v1/compliance/remediation-plans/{plan.id}/approve")
    assert resp.status_code == 403
    await db_session.refresh(plan)
    assert plan.status == "PENDING_APPROVAL"

    current_user["id"] = str(uuid.uuid4())
    resp = await client.post(f"/api/v1/compliance/remediation-plans/{plan.id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXECUTING"


@pytest.mark.asyncio
async def test_plan_creator_with_nanoid_id_cannot_approve_own_plan(
    client: AsyncClient, db_session, current_user, fake_cache, fake_nats
):
    """Better Auth ids are nanoids and never parse as UUID, so created_by stays
    NULL for them; only the raw id stored beside it can match the creator."""
    creator = "k3Xq9wLbz0nanoidA"
    agent = await _make_agent(db_session)
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))
    plan = await svc.create_plan(
        name="self-approve-nanoid",
        trigger_type="MANUAL",
        actions=[
            RemediationActionCreate(agent_id=agent.id, provider="shell", rendered_body="echo fix"),
        ],
        created_by_actor=creator,
    )
    await svc.submit(plan.id, {"id": creator})
    await db_session.commit()

    current_user.update(id=creator, role="OPERATOR")
    resp = await client.post(f"/api/v1/compliance/remediation-plans/{plan.id}/approve")
    assert resp.status_code == 403
    await db_session.refresh(plan)
    assert plan.status == "PENDING_APPROVAL"


# ── Point 6 · server maintenance toggle: role-gated and audited ───────────────


@pytest.mark.asyncio
async def test_viewer_cannot_toggle_maintenance(client: AsyncClient, db_session, current_user):
    current_user["role"] = "VIEWER"
    agent = await _make_agent(db_session)
    await db_session.commit()

    resp = await client.post(f"/api/v1/servers/{agent.id}/maintenance")
    assert resp.status_code == 403
    await db_session.refresh(agent)
    assert agent.status == AgentStatus.ACTIVE


@pytest.mark.asyncio
async def test_operator_maintenance_toggle_writes_audit_row(
    client: AsyncClient, db_session, current_user
):
    actor = str(uuid.uuid4())
    current_user.update(id=actor, role="OPERATOR")
    agent = await _make_agent(db_session)
    await db_session.commit()

    resp = await client.post(f"/api/v1/servers/{agent.id}/maintenance")
    assert resp.status_code == 200
    assert resp.json()["status"] == "MAINTENANCE"

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "agent.maintenance_toggled",
                    AuditLog.resource_id == str(agent.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].user_id == actor


# ── Point 7 · job cancel: same roles that may create jobs ─────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["VIEWER", "AUDITOR"])
async def test_low_privilege_roles_cannot_cancel_job(
    client: AsyncClient, db_session, current_user, role
):
    current_user["role"] = role
    job = Job(name="keep-me", job_type="PACKAGE_UPDATE", target_servers={}, status=JobStatus.QUEUED)
    db_session.add(job)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/jobs/{job.id}")
    assert resp.status_code == 403
    await db_session.refresh(job)
    assert job.status == JobStatus.QUEUED


@pytest.mark.asyncio
async def test_operator_can_cancel_queued_job(client: AsyncClient, db_session, current_user):
    current_user["role"] = "OPERATOR"
    job = Job(
        name="cancel-me",
        job_type="PACKAGE_UPDATE",
        target_servers={},
        status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/jobs/{job.id}")
    assert resp.status_code == 204
    await db_session.refresh(job)
    assert job.status == JobStatus.CANCELLED
