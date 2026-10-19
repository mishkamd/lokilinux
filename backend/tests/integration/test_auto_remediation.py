"""Tests for Enterprise Compliance plan U7 — remediation modes
(MONITOR/ASSISTED/AUTOMATIC): domain allowlist logic, AUTOMATIC eligibility
preconditions, MONITOR enforcement on manual plan creation, and the
policy-set remediation-settings endpoint."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.compliance_rule import (
    ComplianceRule,
    PolicySet,
    PolicySetRule,
    RemediationTemplate,
)
from lokilinux.models.remediation import MaintenanceWindow, RemediationAction, RemediationPlan
from lokilinux.schemas.remediation import RemediationActionCreate
from lokilinux.services.auto_remediation import (
    domain_allowed,
    eligible_for_automatic,
    find_automatic_policy,
    is_monitor_only,
    plans_created_today,
)
from lokilinux.services.job_service import JobService
from lokilinux.services.remediation_service import RemediationService

# ── domain_allowed — pure logic matrix ──────────────────────────────────────


def test_domain_allowed_empty_policy_allows_everything():
    assert domain_allowed(None, "sshd") is True
    assert domain_allowed({}, "sshd") is True


def test_domain_allowed_forbidden_wins_over_allowed():
    assert domain_allowed({"allowed": ["sshd"], "forbidden": ["sshd"]}, "sshd") is False


def test_domain_allowed_nonempty_allowlist_excludes_others():
    remediation = {"allowed": ["sshd", "pam"]}
    assert domain_allowed(remediation, "sshd") is True
    assert domain_allowed(remediation, "sysctl") is False


def test_domain_allowed_forbidden_only_blocks_that_domain():
    remediation = {"forbidden": ["cron"]}
    assert domain_allowed(remediation, "cron") is False
    assert domain_allowed(remediation, "sshd") is True


# ── fixtures ─────────────────────────────────────────────────────────────────


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


async def _policy(db_session, rule: ComplianceRule, remediation: dict | None) -> PolicySet:
    p = PolicySet(
        name=f"policy-{uuid.uuid4().hex[:6]}",
        slug=f"policy-{uuid.uuid4().hex[:6]}",
        framework="INTERNAL",
        remediation=remediation,
    )
    db_session.add(p)
    await db_session.flush()
    db_session.add(PolicySetRule(policy_set_id=p.id, rule_id=rule.id))
    await db_session.commit()
    return p


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


async def _template(
    db_session, rule: ComplianceRule, rollback_body: str | None = "undo"
) -> RemediationTemplate:
    t = RemediationTemplate(
        rule_key=rule.rule_key,
        provider="shell",
        body="echo fix",
        rollback_body=rollback_body,
    )
    db_session.add(t)
    await db_session.commit()
    return t


# ── find_automatic_policy ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_automatic_policy_picks_automatic_among_mixed_modes(db_session):
    rule = await _rule(db_session)
    await _policy(db_session, rule, {"mode": "ASSISTED"})
    automatic = await _policy(db_session, rule, {"mode": "AUTOMATIC"})

    found = await find_automatic_policy(db_session, rule.id)
    assert found is not None
    assert found.id == automatic.id


@pytest.mark.asyncio
async def test_find_automatic_policy_none_when_no_policy_is_automatic(db_session):
    rule = await _rule(db_session)
    await _policy(db_session, rule, {"mode": "ASSISTED"})

    assert await find_automatic_policy(db_session, rule.id) is None


# ── eligible_for_automatic — precondition matrix ────────────────────────────


@pytest.mark.asyncio
async def test_eligible_when_every_precondition_holds(db_session):
    agent = await _agent(db_session)
    rule = await _rule(db_session, domain="sshd")
    policy = await _policy(db_session, rule, {"mode": "AUTOMATIC", "allowed": ["sshd"]})
    await _template(db_session, rule)
    await _open_window(db_session)

    ok, reason = await eligible_for_automatic(db_session, agent.id, rule, policy)
    assert ok is True
    assert reason == ""


@pytest.mark.asyncio
async def test_ineligible_domain_not_allowed(db_session):
    agent = await _agent(db_session)
    rule = await _rule(db_session, domain="sshd")
    policy = await _policy(db_session, rule, {"mode": "AUTOMATIC", "allowed": ["pam"]})
    await _template(db_session, rule)
    await _open_window(db_session)

    ok, reason = await eligible_for_automatic(db_session, agent.id, rule, policy)
    assert ok is False
    assert "allowlist" in reason


@pytest.mark.asyncio
async def test_ineligible_no_template(db_session):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    policy = await _policy(db_session, rule, {"mode": "AUTOMATIC"})
    await _open_window(db_session)

    ok, reason = await eligible_for_automatic(db_session, agent.id, rule, policy)
    assert ok is False
    assert "template" in reason


@pytest.mark.asyncio
async def test_ineligible_template_without_rollback(db_session):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    policy = await _policy(db_session, rule, {"mode": "AUTOMATIC"})
    await _template(db_session, rule, rollback_body=None)
    await _open_window(db_session)

    ok, reason = await eligible_for_automatic(db_session, agent.id, rule, policy)
    assert ok is False
    assert "rollback" in reason


@pytest.mark.asyncio
async def test_ineligible_no_open_maintenance_window(db_session):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    policy = await _policy(db_session, rule, {"mode": "AUTOMATIC"})
    await _template(db_session, rule)
    # no window at all

    ok, reason = await eligible_for_automatic(db_session, agent.id, rule, policy)
    assert ok is False
    assert "maintenance window" in reason


@pytest.mark.asyncio
async def test_ineligible_plan_already_executing_for_same_agent_rule(db_session):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    policy = await _policy(db_session, rule, {"mode": "AUTOMATIC"})
    await _template(db_session, rule)
    await _open_window(db_session)

    plan = RemediationPlan(name="already running", status="EXECUTING", trigger_type="MANUAL")
    db_session.add(plan)
    await db_session.flush()
    db_session.add(
        RemediationAction(
            remediation_plan_id=plan.id,
            agent_id=agent.id,
            sequence=0,
            provider="shell",
            rendered_body="echo x",
            rule_id=rule.id,
        )
    )
    await db_session.commit()

    ok, reason = await eligible_for_automatic(db_session, agent.id, rule, policy)
    assert ok is False
    assert "already executing" in reason


# ── is_monitor_only ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_monitor_only_true_when_every_covering_policy_is_monitor(db_session):
    rule = await _rule(db_session)
    await _policy(db_session, rule, {"mode": "MONITOR"})
    assert await is_monitor_only(db_session, rule.id) is True


@pytest.mark.asyncio
async def test_is_monitor_only_false_when_an_assisted_policy_also_covers_it(db_session):
    rule = await _rule(db_session)
    await _policy(db_session, rule, {"mode": "MONITOR"})
    await _policy(db_session, rule, {"mode": "ASSISTED"})
    assert await is_monitor_only(db_session, rule.id) is False


@pytest.mark.asyncio
async def test_is_monitor_only_false_when_rule_has_no_covering_policy(db_session):
    rule = await _rule(db_session)
    assert await is_monitor_only(db_session, rule.id) is False


# ── MONITOR enforcement on manual plan creation ─────────────────────────────


@pytest.mark.asyncio
async def test_create_plan_rejects_monitor_only_rule(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _policy(db_session, rule, {"mode": "MONITOR"})
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))

    with pytest.raises(Exception) as exc_info:
        await svc.create_plan(
            name="blocked",
            trigger_type="MANUAL",
            actions=[
                RemediationActionCreate(
                    agent_id=agent.id, provider="shell", rendered_body="echo x", rule_id=rule.id
                )
            ],
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_plan_allows_assisted_rule(db_session, fake_cache, fake_nats):
    agent = await _agent(db_session)
    rule = await _rule(db_session)
    await _policy(db_session, rule, {"mode": "ASSISTED"})
    svc = RemediationService(db_session, JobService(db_session, fake_cache, fake_nats))

    plan = await svc.create_plan(
        name="allowed",
        trigger_type="MANUAL",
        actions=[
            RemediationActionCreate(
                agent_id=agent.id, provider="shell", rendered_body="echo x", rule_id=rule.id
            )
        ],
    )
    assert plan.status == "DRAFT"


# ── plans_created_today ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plans_created_today_counts_only_automatic_trigger_type(db_session):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    db_session.add_all(
        [
            RemediationPlan(name="auto1", status="DRAFT", trigger_type="AUTOMATIC"),
            RemediationPlan(name="auto2", status="DRAFT", trigger_type="AUTOMATIC"),
            RemediationPlan(name="manual", status="DRAFT", trigger_type="MANUAL"),
        ]
    )
    await db_session.commit()

    assert await plans_created_today(db_session, today_start) == 2


# ── PATCH /policy-sets/{id}/remediation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_set_policy_remediation_persists_and_audits(
    client: AsyncClient, db_session: AsyncSession
):
    policy = PolicySet(name="p1", slug=f"p1-{uuid.uuid4().hex[:6]}", framework="INTERNAL")
    db_session.add(policy)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/compliance/policy-sets/{policy.id}/remediation",
        json={"mode": "AUTOMATIC", "allowed": ["sshd"], "forbidden": ["cron"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["remediation"] == {"mode": "AUTOMATIC", "allowed": ["sshd"], "forbidden": ["cron"]}

    from sqlalchemy import select

    from lokilinux.models.audit import AuditLog

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "compliance.policy_set_remediation_updated"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_set_policy_remediation_rejects_invalid_mode(
    client: AsyncClient, db_session: AsyncSession
):
    policy = PolicySet(name="p2", slug=f"p2-{uuid.uuid4().hex[:6]}", framework="INTERNAL")
    db_session.add(policy)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/compliance/policy-sets/{policy.id}/remediation",
        json={"mode": "BOGUS"},
    )
    assert resp.status_code == 422
