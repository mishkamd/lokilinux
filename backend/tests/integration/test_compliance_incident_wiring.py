"""Integration tests for Enterprise Compliance plan U6 — incident state
wiring: remediation EXECUTING/FAILED/ROLLED_BACK and exception APPROVED
both reflect onto drift_events instead of leaving phantom OPEN/IN_REMEDIATION
state behind."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.compliance_exception import ComplianceException
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.drift import DriftEvent
from lokilinux.models.job import Job, JobStatus
from lokilinux.models.remediation import RemediationJob
from lokilinux.schemas.remediation import RemediationActionCreate
from lokilinux.services.compliance_exception_service import ExceptionService
from lokilinux.services.job_service import JobService, _sync_remediation_plan
from lokilinux.services.remediation_service import RemediationService
from lokilinux.workers.remediation_verification import RemediationVerificationWorker


async def _agent(db_session) -> Agent:
    a = Agent(
        agent_id=f"test-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(a)
    await db_session.flush()
    return a


async def _rule(db_session, domain: str = "sshd") -> ComplianceRule:
    r = ComplianceRule(
        rule_key=f"rule-{uuid.uuid4()}",
        title="A rule",
        severity="HIGH",
        domain=domain,
        check_source="CEL",
        check_expr="true",
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _open_drift(db_session, agent: Agent, domain: str = "sshd") -> DriftEvent:
    d = DriftEvent(
        time=datetime.now(timezone.utc),
        agent_id=agent.id,
        id=uuid.uuid4(),
        domain=domain,
        compared_against="BASELINE",
        severity="HIGH",
        change_type="MODIFIED",
        summary="drifted",
        status="OPEN",
    )
    db_session.add(d)
    await db_session.commit()
    return d


@pytest.mark.asyncio
async def test_dispatch_sets_referenced_drift_to_in_remediation(
    db_session, fake_cache, fake_nats, current_user
):
    agent = await _agent(db_session)
    drift = await _open_drift(db_session, agent)
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))

    plan = await svc.create_plan(
        name="Fix sshd",
        trigger_type="MANUAL",
        actions=[
            RemediationActionCreate(
                agent_id=agent.id,
                provider="shell",
                rendered_body="echo fix",
                drift_event_id=drift.id,
            )
        ],
    )
    await svc.submit(plan.id, current_user)
    approved = await svc.approve(plan.id, current_user)
    assert approved.status == "EXECUTING"

    await db_session.refresh(drift)
    assert drift.status == "IN_REMEDIATION"


@pytest.mark.asyncio
async def test_failed_apply_job_reverts_drift_to_open(
    db_session, fake_cache, fake_nats, current_user
):
    agent = await _agent(db_session)
    drift = await _open_drift(db_session, agent)
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))
    plan = await svc.create_plan(
        name="Fix sshd",
        trigger_type="MANUAL",
        actions=[
            RemediationActionCreate(
                agent_id=agent.id,
                provider="shell",
                rendered_body="echo fix",
                drift_event_id=drift.id,
            )
        ],
    )
    await svc.submit(plan.id, current_user)
    await svc.approve(plan.id, current_user)
    await db_session.refresh(drift)
    assert drift.status == "IN_REMEDIATION"

    link = (
        await db_session.execute(
            select(RemediationJob).where(RemediationJob.remediation_plan_id == plan.id)
        )
    ).scalar_one()
    job = await db_session.get(Job, link.job_id)
    job.status = JobStatus.FAILED
    job.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    await _sync_remediation_plan(db_session, job)
    await db_session.commit()

    await db_session.refresh(plan)
    await db_session.refresh(drift)
    assert plan.status == "FAILED"
    assert drift.status == "OPEN"


@pytest.mark.asyncio
async def test_rollback_completed_reverts_drift_to_open(db_session):
    agent = await _agent(db_session)
    drift = await _open_drift(db_session, agent)
    drift.status = "IN_REMEDIATION"
    await db_session.commit()

    from lokilinux.models.remediation import RemediationAction, RemediationPlan

    plan = RemediationPlan(name="Rollback test", status="COMPLETED", trigger_type="MANUAL")
    db_session.add(plan)
    await db_session.flush()
    db_session.add(
        RemediationAction(
            remediation_plan_id=plan.id,
            agent_id=agent.id,
            sequence=0,
            provider="shell",
            rendered_body="echo fix",
            drift_event_id=drift.id,
        )
    )
    job = Job(
        name="rollback",
        job_type="COMPLIANCE_REMEDIATE",
        status=JobStatus.COMPLETED,
        target_servers={"agent_ids": [str(agent.id)]},
        parameters={"remediation_plan_id": str(plan.id), "operation": "ROLLBACK"},
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(RemediationJob(remediation_plan_id=plan.id, job_id=job.id))
    await db_session.commit()

    await _sync_remediation_plan(db_session, job)
    await db_session.commit()

    await db_session.refresh(plan)
    await db_session.refresh(drift)
    assert plan.status == "ROLLED_BACK"
    assert drift.status == "OPEN"


@pytest.mark.asyncio
async def test_verification_fail_reverts_drift_and_completed_resolves_it(db_session):
    from lokilinux.models.remediation import RemediationAction, RemediationPlan
    from lokilinux.models.rule_evaluation import RuleEvaluation

    agent = await _agent(db_session)
    rule = await _rule(db_session, domain="sshd")
    drift = await _open_drift(db_session, agent, domain="sshd")
    drift.status = "IN_REMEDIATION"
    await db_session.commit()

    plan = RemediationPlan(name="Verify test", status="VERIFYING", trigger_type="MANUAL")
    db_session.add(plan)
    await db_session.flush()
    db_session.add(
        RemediationAction(
            remediation_plan_id=plan.id,
            agent_id=agent.id,
            sequence=0,
            provider="shell",
            rendered_body="echo fix",
            rule_id=rule.id,
            drift_event_id=drift.id,
        )
    )
    completed_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    job = Job(
        name="apply",
        job_type="COMPLIANCE_REMEDIATE",
        status=JobStatus.COMPLETED,
        target_servers={"agent_ids": [str(agent.id)]},
        parameters={"remediation_plan_id": str(plan.id), "operation": "APPLY"},
        completed_at=completed_at,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(RemediationJob(remediation_plan_id=plan.id, job_id=job.id))
    db_session.add(
        RuleEvaluation(
            time=datetime.now(timezone.utc),
            agent_id=agent.id,
            rule_id=rule.id,
            policy_set_id=uuid.uuid4(),
            result="FAIL",
        )
    )
    await db_session.commit()

    worker = RemediationVerificationWorker(lambda: db_session)
    await worker._verify_plan(db_session, plan)

    await db_session.refresh(plan)
    await db_session.refresh(drift)
    assert plan.status == "FAILED"
    assert drift.status == "OPEN"


@pytest.mark.asyncio
async def test_exception_approve_closes_open_drift_for_scoped_agent(db_session, current_user):
    agent = await _agent(db_session)
    rule = await _rule(db_session, domain="sshd")
    drift = await _open_drift(db_session, agent, domain="sshd")

    exc = ComplianceException(
        rule_id=rule.id,
        agent_id=agent.id,
        reason="known false positive",
        owner="ops-team",
        status="PENDING",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(exc)
    await db_session.commit()

    actor_id = uuid.UUID(current_user["id"])
    await ExceptionService(db_session).approve(exc, current_user, actor_id)

    await db_session.refresh(drift)
    assert drift.status == "EXCEPTION"
    assert drift.suppressed_by == actor_id


@pytest.mark.asyncio
async def test_exception_approve_fleet_wide_closes_all_open_drift_on_domain(
    db_session, current_user
):
    agent_a = await _agent(db_session)
    agent_b = await _agent(db_session)
    rule = await _rule(db_session, domain="pam")
    drift_a = await _open_drift(db_session, agent_a, domain="pam")
    drift_b = await _open_drift(db_session, agent_b, domain="pam")

    exc = ComplianceException(
        rule_id=rule.id,
        agent_id=None,
        reason="fleet-wide waiver",
        owner="ops-team",
        status="PENDING",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(exc)
    await db_session.commit()

    await ExceptionService(db_session).approve(exc, current_user, uuid.UUID(current_user["id"]))

    await db_session.refresh(drift_a)
    await db_session.refresh(drift_b)
    assert drift_a.status == "EXCEPTION"
    assert drift_b.status == "EXCEPTION"


@pytest.mark.asyncio
async def test_exception_approve_skips_scoped_fleet_exception_without_crashing(
    db_session, current_user
):
    """ponytail gap, documented in compliance_exception_service.py: a
    fleet-wide exception narrowed by scope_selector has no Python-side
    agent-attribute matcher yet — this must not touch drift or error."""
    agent = await _agent(db_session)
    rule = await _rule(db_session, domain="cron")
    drift = await _open_drift(db_session, agent, domain="cron")

    exc = ComplianceException(
        rule_id=rule.id,
        agent_id=None,
        scope_selector={"tag": "prod"},
        reason="scoped waiver",
        owner="ops-team",
        status="PENDING",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(exc)
    await db_session.commit()

    updated = await ExceptionService(db_session).approve(
        exc, current_user, uuid.UUID(current_user["id"])
    )
    assert updated.status == "ACTIVE"

    await db_session.refresh(drift)
    assert drift.status == "OPEN"
