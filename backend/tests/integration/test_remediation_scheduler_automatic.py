"""Tests for RemediationSchedulerWorker's AUTOMATIC-mode closed loop
(Enterprise Compliance plan U7/KTD8, Autopilot A2): finding -> plan ->
mandatory dry-run -> auto-approve/dispatch, and the FAILED path when the
dry-run itself fails. Calls the worker's tick methods directly against a
real db_session rather than running the asyncio loop — same style as
test_auto_remediation.py's direct calls into eligible_for_automatic."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.audit import AuditLog
from lokilinux.models.compliance_rule import (
    ComplianceRule,
    PolicySet,
    PolicySetRule,
    RemediationTemplate,
)
from lokilinux.models.job import Job, JobStatus
from lokilinux.models.remediation import MaintenanceWindow, RemediationJob, RemediationPlan
from lokilinux.models.rule_evaluation import RuleEvaluation
from lokilinux.workers.remediation_scheduler import RemediationSchedulerWorker


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
        status="ACTIVE",
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _automatic_policy(db_session, rule: ComplianceRule, **remediation_extra) -> PolicySet:
    p = PolicySet(
        name=f"policy-{uuid.uuid4().hex[:6]}",
        slug=f"policy-{uuid.uuid4().hex[:6]}",
        framework="INTERNAL",
        remediation={"mode": "AUTOMATIC", **remediation_extra},
    )
    db_session.add(p)
    await db_session.flush()
    db_session.add(PolicySetRule(policy_set_id=p.id, rule_id=rule.id))
    await db_session.commit()
    return p


async def _template(db_session, rule: ComplianceRule) -> RemediationTemplate:
    t = RemediationTemplate(
        rule_key=rule.rule_key, provider="shell", body="echo fix", rollback_body="echo undo"
    )
    db_session.add(t)
    await db_session.commit()
    return t


async def _open_window(db_session) -> MaintenanceWindow:
    w = MaintenanceWindow(
        name="always-open",
        scope_type="GLOBAL",
        scope_selector={"all": True},
        cron_expr="* * * * *",
        duration_minutes=1440,
        timezone="UTC",
    )
    db_session.add(w)
    await db_session.commit()
    return w


async def _failing_finding(db_session, agent: Agent, rule: ComplianceRule) -> None:
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


async def _set_auto_remediation_enabled(db_session, enabled: bool, max_per_day: int = 10) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from lokilinux.models.audit import Setting

    for key, value, vtype in (
        ("compliance.auto_remediation_enabled", "true" if enabled else "false", "boolean"),
        ("compliance.auto_remediation_max_plans_per_day", str(max_per_day), "integer"),
    ):
        await db_session.execute(
            pg_insert(Setting)
            .values(key=key, value=value, value_type=vtype)
            .on_conflict_do_update(index_elements=["key"], set_={"value": value})
        )
    await db_session.commit()


async def _automatic_plans(db_session) -> list[RemediationPlan]:
    return (
        (
            await db_session.execute(
                select(RemediationPlan).where(RemediationPlan.trigger_type == "AUTOMATIC")
            )
        )
        .scalars()
        .all()
    )


async def _dry_run_job_for(db_session, plan_id) -> Job | None:
    link = (
        (
            await db_session.execute(
                select(RemediationJob).where(RemediationJob.remediation_plan_id == plan_id)
            )
        )
        .scalars()
        .first()
    )
    if link is None:
        return None
    return await db_session.get(Job, link.job_id)


def _worker(fake_cache, fake_nats) -> RemediationSchedulerWorker:
    return RemediationSchedulerWorker(db_session_factory=None, cache=fake_cache, nats=fake_nats)


# ── kill-switch ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tick_automatic_noop_when_kill_switch_off(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _automatic_policy(db_session, rule)
    await _template(db_session, rule)
    await _open_window(db_session)
    await _failing_finding(db_session, agent, rule)
    await _set_auto_remediation_enabled(db_session, False)

    await _worker(fake_cache, fake_nats)._tick_automatic(db_session, datetime.now(timezone.utc))

    assert await _automatic_plans(db_session) == []


# ── trigger: eligible finding -> DRAFT plan + dry-run job ──────────────────


@pytest.mark.asyncio
async def test_trigger_creates_draft_plan_and_dry_run_job(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _automatic_policy(db_session, rule, allowed=["sshd"])
    await _template(db_session, rule)
    await _open_window(db_session)
    await _failing_finding(db_session, agent, rule)
    await _set_auto_remediation_enabled(db_session, True)

    await _worker(fake_cache, fake_nats)._tick_automatic(db_session, datetime.now(timezone.utc))

    plans = await _automatic_plans(db_session)
    assert len(plans) == 1
    assert plans[0].status == "DRAFT"

    job = await _dry_run_job_for(db_session, plans[0].id)
    assert job is not None
    assert job.job_type == "COMPLIANCE_REMEDIATE"
    assert (job.parameters or {}).get("operation") == "DRY_RUN"


@pytest.mark.asyncio
async def test_trigger_skips_ineligible_finding_no_template(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _automatic_policy(db_session, rule)
    await _open_window(db_session)
    await _failing_finding(db_session, agent, rule)
    await _set_auto_remediation_enabled(db_session, True)

    await _worker(fake_cache, fake_nats)._tick_automatic(db_session, datetime.now(timezone.utc))

    assert await _automatic_plans(db_session) == []


@pytest.mark.asyncio
async def test_trigger_respects_daily_cap(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _automatic_policy(db_session, rule)
    await _template(db_session, rule)
    await _open_window(db_session)
    await _failing_finding(db_session, agent, rule)
    await _set_auto_remediation_enabled(db_session, True, max_per_day=0)

    await _worker(fake_cache, fake_nats)._tick_automatic(db_session, datetime.now(timezone.utc))

    assert await _automatic_plans(db_session) == []


@pytest.mark.asyncio
async def test_trigger_does_not_duplicate_within_same_day(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _automatic_policy(db_session, rule)
    await _template(db_session, rule)
    await _open_window(db_session)
    await _failing_finding(db_session, agent, rule)
    await _set_auto_remediation_enabled(db_session, True)

    worker = _worker(fake_cache, fake_nats)
    now = datetime.now(timezone.utc)
    await worker._tick_automatic(db_session, now)
    await worker._tick_automatic(
        db_session, now
    )  # still failing next tick — must not double-trigger

    assert len(await _automatic_plans(db_session)) == 1


# ── resolve: dry-run outcome ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_completed_dry_run_dispatches_plan(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _automatic_policy(db_session, rule)
    await _template(db_session, rule)
    await _open_window(db_session)
    await _failing_finding(db_session, agent, rule)
    await _set_auto_remediation_enabled(db_session, True)

    worker = _worker(fake_cache, fake_nats)
    now = datetime.now(timezone.utc)
    await worker._tick_automatic(db_session, now)

    plan = (await _automatic_plans(db_session))[0]
    job = await _dry_run_job_for(db_session, plan.id)
    job.status = JobStatus.COMPLETED
    await db_session.commit()

    await worker._tick_automatic(db_session, now)

    await db_session.refresh(plan)
    assert plan.status == "EXECUTING"


@pytest.mark.asyncio
async def test_resolve_failed_dry_run_fails_plan_without_dispatch(
    db_session, fake_cache, fake_nats
):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _automatic_policy(db_session, rule)
    await _template(db_session, rule)
    await _open_window(db_session)
    await _failing_finding(db_session, agent, rule)
    await _set_auto_remediation_enabled(db_session, True)

    worker = _worker(fake_cache, fake_nats)
    now = datetime.now(timezone.utc)
    await worker._tick_automatic(db_session, now)

    plan = (await _automatic_plans(db_session))[0]
    job = await _dry_run_job_for(db_session, plan.id)
    job.status = JobStatus.FAILED
    await db_session.commit()

    await worker._tick_automatic(db_session, now)

    await db_session.refresh(plan)
    assert plan.status == "FAILED"

    logs = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "compliance.remediation_plan_auto_failed")
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].changes["reason"] == "dry-run failed"


@pytest.mark.asyncio
async def test_resolve_leaves_still_running_dry_run_untouched(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _automatic_policy(db_session, rule)
    await _template(db_session, rule)
    await _open_window(db_session)
    await _failing_finding(db_session, agent, rule)
    await _set_auto_remediation_enabled(db_session, True)

    worker = _worker(fake_cache, fake_nats)
    now = datetime.now(timezone.utc)
    await worker._tick_automatic(db_session, now)

    plan = (await _automatic_plans(db_session))[0]

    await worker._tick_automatic(db_session, now)  # job still QUEUED/RUNNING

    await db_session.refresh(plan)
    assert plan.status == "DRAFT"


@pytest.mark.asyncio
async def test_resolve_fails_plan_when_dry_run_never_dispatched(db_session, fake_cache, fake_nats):
    stale = RemediationPlan(
        name="stuck",
        status="DRAFT",
        trigger_type="AUTOMATIC",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add(stale)
    await db_session.commit()

    worker = _worker(fake_cache, fake_nats)
    await worker._resolve_pending_dry_runs(db_session, datetime.now(timezone.utc))

    await db_session.refresh(stale)
    assert stale.status == "FAILED"
