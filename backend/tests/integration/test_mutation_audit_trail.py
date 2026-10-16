"""MIS-41: compliance mutations write an audit_logs row next to the commit.

One test per route family (assessments, reports, fim_scopes, remediation-plans,
maintenance-windows), plus the AUTOMATIC remediation trigger, which runs in the
scheduler rather than a route. Each asserts the row exists and is tied to the
resource it created or changed.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.audit import AuditLog, Setting
from lokilinux.models.compliance_rule import (
    ComplianceRule,
    PolicySet,
    PolicySetRule,
    RemediationTemplate,
)
from lokilinux.models.remediation import MaintenanceWindow, RemediationPlan
from lokilinux.models.rule_evaluation import RuleEvaluation
from lokilinux.workers.remediation_scheduler import RemediationSchedulerWorker

API = "/api/v1/compliance"


async def _audit_rows(db_session, action: str, resource_id: str) -> list[AuditLog]:
    return (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == action, AuditLog.resource_id == resource_id
                )
            )
        )
        .scalars()
        .all()
    )


async def _agent(db_session) -> Agent:
    agent = Agent(
        agent_id=str(uuid.uuid4()),
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_create_assessment_writes_audit_row(client: AsyncClient, db_session, current_user):
    policy = PolicySet(
        id=uuid.uuid4(), name="audit", slug=f"audit-{uuid.uuid4().hex[:8]}", framework="INTERNAL"
    )
    db_session.add(policy)
    await db_session.commit()

    resp = await client.post(f"{API}/assessments", json={"policy_set_id": str(policy.id)})
    assert resp.status_code == 202

    rows = await _audit_rows(db_session, "compliance.assessment_created", resp.json()["id"])
    assert len(rows) == 1
    assert rows[0].user_id == current_user["id"]


@pytest.mark.asyncio
async def test_create_report_writes_audit_row(client: AsyncClient, db_session, current_user):
    resp = await client.post(
        f"{API}/reports",
        json={"report_type": "FLEET_SUMMARY", "format": "JSON", "params": {}},
    )
    assert resp.status_code == 202

    rows = await _audit_rows(db_session, "compliance.report_created", resp.json()["id"])
    assert len(rows) == 1
    assert rows[0].user_id == current_user["id"]


@pytest.mark.asyncio
async def test_fim_scope_mutations_write_audit_rows(client: AsyncClient, db_session, current_user):
    agent = await _agent(db_session)
    await db_session.commit()
    body = {"watch_paths": ["/etc/ssh"], "ignore_paths": []}

    resp = await client.put(f"{API}/fim-scopes", json=body)
    assert resp.status_code == 200
    rows = await _audit_rows(db_session, "compliance.fim_scope_updated", "GLOBAL")
    assert len(rows) == 1
    assert rows[0].user_id == current_user["id"]

    resp = await client.put(f"{API}/fim-scopes/{agent.id}", json=body)
    assert resp.status_code == 200
    rows = await _audit_rows(db_session, "compliance.fim_scope_updated", str(agent.id))
    assert len(rows) == 1

    resp = await client.delete(f"{API}/fim-scopes/{agent.id}")
    assert resp.status_code == 204
    rows = await _audit_rows(db_session, "compliance.fim_scope_deleted", str(agent.id))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_create_remediation_plan_writes_audit_row(
    client: AsyncClient, db_session, current_user
):
    agent = await _agent(db_session)
    await db_session.commit()

    resp = await client.post(
        f"{API}/remediation-plans",
        json={
            "name": "audit me",
            "trigger_type": "MANUAL",
            "actions": [
                {"agent_id": str(agent.id), "provider": "shell", "rendered_body": "echo fix"}
            ],
        },
    )
    assert resp.status_code == 201

    rows = await _audit_rows(db_session, "compliance.remediation_plan_created", resp.json()["id"])
    assert len(rows) == 1
    assert rows[0].user_id == current_user["id"]


@pytest.mark.asyncio
async def test_create_maintenance_window_writes_audit_row(
    client: AsyncClient, db_session, current_user
):
    resp = await client.post(
        f"{API}/maintenance-windows",
        json={"name": "nightly", "cron_expr": "0 2 * * *", "duration_minutes": 60},
    )
    assert resp.status_code == 201

    rows = await _audit_rows(db_session, "compliance.maintenance_window_created", resp.json()["id"])
    assert len(rows) == 1
    assert rows[0].user_id == current_user["id"]


@pytest.mark.asyncio
async def test_automatic_remediation_trigger_writes_audit_row(db_session, fake_cache, fake_nats):
    """Scheduler path: an eligible FAIL finding creates an AUTOMATIC plan.
    Already audited in remediation_scheduler._create_automatic_plan — this is
    the regression guard for the auto_remediation acceptance item."""
    agent = await _agent(db_session)
    rule = ComplianceRule(
        rule_key=f"rule-{uuid.uuid4()}",
        title="A rule",
        severity="HIGH",
        domain="sshd",
        check_source="CEL",
        check_expr="true",
        status="ACTIVE",
    )
    db_session.add(rule)
    await db_session.flush()
    policy = PolicySet(
        id=uuid.uuid4(),
        name="auto",
        slug=f"auto-{uuid.uuid4().hex[:8]}",
        framework="INTERNAL",
        remediation={"mode": "AUTOMATIC", "allowed": ["sshd"]},
    )
    db_session.add(policy)
    await db_session.flush()
    db_session.add(PolicySetRule(policy_set_id=policy.id, rule_id=rule.id))
    db_session.add(
        RemediationTemplate(
            rule_key=rule.rule_key, provider="shell", body="echo fix", rollback_body="echo undo"
        )
    )
    db_session.add(
        MaintenanceWindow(
            name="always-open",
            scope_type="GLOBAL",
            scope_selector={"all": True},
            cron_expr="* * * * *",
            duration_minutes=1440,
            timezone="UTC",
        )
    )
    db_session.add(
        RuleEvaluation(
            time=datetime.now(timezone.utc),
            agent_id=agent.id,
            rule_id=rule.id,
            policy_set_id=uuid.uuid4(),
            result="FAIL",
        )
    )
    for key, value, vtype in (
        ("compliance.auto_remediation_enabled", "true", "boolean"),
        ("compliance.auto_remediation_max_plans_per_day", "10", "integer"),
    ):
        await db_session.execute(
            pg_insert(Setting)
            .values(key=key, value=value, value_type=vtype)
            .on_conflict_do_update(index_elements=["key"], set_={"value": value})
        )
    await db_session.commit()

    worker = RemediationSchedulerWorker(db_session_factory=None, cache=fake_cache, nats=fake_nats)
    await worker._tick_automatic(db_session, datetime.now(timezone.utc))

    plan = (
        (
            await db_session.execute(
                select(RemediationPlan).where(RemediationPlan.trigger_type == "AUTOMATIC")
            )
        )
        .scalars()
        .one()
    )
    rows = await _audit_rows(db_session, "compliance.remediation_plan_auto_triggered", str(plan.id))
    assert len(rows) == 1
