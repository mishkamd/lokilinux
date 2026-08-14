"""Unit tests for RemediationService: plan creation, approve/dispatch, rollback."""

import uuid

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.job import Job
from lokilinux.models.remediation import RemediationAction, RemediationJob
from lokilinux.schemas.remediation import RemediationActionCreate
from lokilinux.services.job_service import JobService
from lokilinux.services.remediation_service import RemediationService, build_actions_payload


async def _make_agent(db_session, agent_id_str: str | None = None) -> Agent:
    agent = Agent(
        agent_id=agent_id_str or f"test-agent-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_create_plan_persists_actions(db_session, fake_cache, fake_nats, current_user):
    agent = await _make_agent(db_session)
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))

    actions = [
        RemediationActionCreate(agent_id=agent.id, provider="shell", rendered_body="echo hello"),
    ]
    plan = await svc.create_plan(
        name="Test plan", trigger_type="MANUAL", actions=actions,
        is_emergency=False, created_by=uuid.UUID(current_user["id"]),
    )

    assert plan.status == "DRAFT"
    rows = (await db_session.execute(
        select(RemediationAction).where(RemediationAction.remediation_plan_id == plan.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].provider == "shell"
    assert rows[0].rendered_body == "echo hello"
    assert rows[0].sequence == 0


@pytest.mark.asyncio
async def test_approve_creates_job_with_correct_payload(db_session, fake_cache, fake_nats, current_user):
    agent = await _make_agent(db_session)
    job_svc = JobService(db_session, fake_cache, fake_nats)
    svc = RemediationService(db_session, job_svc)

    actions = [
        RemediationActionCreate(agent_id=agent.id, provider="shell", rendered_body="echo fix"),
    ]
    plan = await svc.create_plan(name="Approve test", trigger_type="MANUAL", actions=actions)
    await svc.submit(plan.id, current_user)

    approved = await svc.approve(plan.id, current_user)
    assert approved.status == "EXECUTING"
    assert approved.approved_by is not None
    assert approved.approved_at is not None

    # Verify the Job was created with correct payload
    link = (await db_session.execute(
        select(RemediationJob).where(RemediationJob.remediation_plan_id == plan.id)
    )).scalar_one()
    job = await db_session.get(Job, link.job_id)
    assert job is not None
    assert job.job_type == "COMPLIANCE_REMEDIATE"
    assert str(agent.id) in job.target_servers["agent_ids"]
    assert job.parameters["operation"] == "APPLY"
    assert job.parameters["remediation_plan_id"] == str(plan.id)
    agent_actions = job.parameters["actions"][str(agent.id)]
    assert len(agent_actions) == 1
    assert agent_actions[0]["rendered_body"] == "echo fix"
    assert agent_actions[0]["provider"] == "shell"


@pytest.mark.asyncio
async def test_build_actions_payload_sorts_by_sequence(db_session, fake_cache, fake_nats):
    agent = await _make_agent(db_session)
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))

    actions = [
        RemediationActionCreate(agent_id=agent.id, provider="shell", rendered_body="second"),
        RemediationActionCreate(agent_id=agent.id, provider="python", rendered_body="first"),
    ]
    plan = await svc.create_plan(name="Seq test", trigger_type="MANUAL", actions=actions)

    db_actions = (await db_session.execute(
        select(RemediationAction).where(RemediationAction.remediation_plan_id == plan.id)
    )).scalars().all()

    payload = build_actions_payload(db_actions)
    agent_key = str(agent.id)
    assert len(payload[agent_key]) == 2
    # Actions should be sorted by sequence ascending
    assert payload[agent_key][0]["sequence"] == 0
    assert payload[agent_key][0]["rendered_body"] == "second"
    assert payload[agent_key][1]["sequence"] == 1
    assert payload[agent_key][1]["rendered_body"] == "first"


@pytest.mark.asyncio
async def test_rollback_requires_completed_or_failed(db_session, fake_cache, fake_nats, current_user):
    agent = await _make_agent(db_session)
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))

    actions = [
        RemediationActionCreate(
            agent_id=agent.id, provider="shell", rendered_body="fix",
            rollback_body="undo",
        ),
    ]
    plan = await svc.create_plan(name="Rollback test", trigger_type="MANUAL", actions=actions)
    await svc.submit(plan.id, current_user)

    # Plan is PENDING_APPROVAL, rollback should fail with 409
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await svc.rollback(plan.id, current_user)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_maintenance_window_id_persisted(db_session, fake_cache, fake_nats, current_user):
    from lokilinux.models.remediation import MaintenanceWindow
    agent = await _make_agent(db_session)

    window = MaintenanceWindow(
        name="Test window", scope_type="GLOBAL", scope_selector={},
        cron_expr="0 2 * * 0", duration_minutes=60, timezone="UTC", is_enabled=True,
    )
    db_session.add(window)
    await db_session.flush()

    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))
    actions = [
        RemediationActionCreate(agent_id=agent.id, provider="shell", rendered_body="echo test"),
    ]
    plan = await svc.create_plan(
        name="Window test", trigger_type="MANUAL", actions=actions,
        maintenance_window_id=window.id,
    )

    assert plan.maintenance_window_id == window.id

    # Verify response schema includes maintenance_window_id
    from lokilinux.schemas.remediation import RemediationPlanResponse
    resp = RemediationPlanResponse.model_validate(plan)
    assert resp.maintenance_window_id == window.id
