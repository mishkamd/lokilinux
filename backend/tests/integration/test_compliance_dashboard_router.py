"""Integration tests for /api/v1/compliance/dashboard — fleet-wide widgets."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.agent import Agent
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.drift import DriftEvent
from lokilinux.models.file_integrity import FileChange
from lokilinux.models.remediation import RemediationAction, RemediationPlan
from lokilinux.models.rule_evaluation import RuleEvaluation


def _agent(agent_id: uuid.UUID, distro: str = "ol") -> Agent:
    return Agent(
        id=agent_id,
        agent_id=str(agent_id),
        hostname=f"test-{agent_id}",
        os_distro=distro,
        os_version="9",
    )


async def _clean(db: AsyncSession) -> None:
    await db.execute(delete(RuleEvaluation))
    await db.execute(delete(FileChange))
    await db.execute(delete(DriftEvent))
    await db.execute(delete(ComplianceRule))
    await db.execute(delete(Agent))
    await db.commit()


@pytest.mark.asyncio
async def test_top_violations_ranks_rules_by_fail_count(
    client: AsyncClient, db_session: AsyncSession
):
    await _clean(db_session)
    agent_a = uuid.uuid4()
    agent_b = uuid.uuid4()
    rule = ComplianceRule(
        id=uuid.uuid4(),
        rule_key="sshd_disable_root_login",
        title="Disable SSH root login",
        severity="HIGH",
        domain="sshd",
        check_source="CEL",
        check_expr="facts.PermitRootLogin == 'no'",
    )
    quiet_rule = ComplianceRule(
        id=uuid.uuid4(),
        rule_key="sysctl_something",
        title="Quiet rule",
        severity="MEDIUM",
        domain="sysctl",
        check_source="CEL",
        check_expr="true",
    )
    db_session.add_all([_agent(agent_a), _agent(agent_b), rule, quiet_rule])
    await db_session.commit()

    now = datetime.now(timezone.utc)
    policy_set_id = uuid.uuid4()
    insert_idx = 0
    for agent_id, count in ((agent_a, 2), (agent_b, 1)):
        for _ in range(count):
            db_session.add(
                RuleEvaluation(
                    time=now + timedelta(microseconds=insert_idx),
                    agent_id=agent_id,
                    rule_id=rule.id,
                    policy_set_id=policy_set_id,
                    result="FAIL",
                )
            )
            insert_idx += 1
    # A PASS on the quiet rule and a FAIL on it from a second agent — the
    # FAIL should rank it second, not tie with the PASS.
    db_session.add(
        RuleEvaluation(
            time=now + timedelta(microseconds=insert_idx),
            agent_id=agent_a,
            rule_id=quiet_rule.id,
            policy_set_id=policy_set_id,
            result="PASS",
        )
    )
    db_session.add(
        RuleEvaluation(
            time=now + timedelta(microseconds=insert_idx + 1),
            agent_id=agent_b,
            rule_id=quiet_rule.id,
            policy_set_id=policy_set_id,
            result="FAIL",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/dashboard/top-violations")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["top_rules"]) == 2
    first, second = body["top_rules"]
    assert first["rule_key"] == "sshd_disable_root_login"
    assert first["fail_count"] == 3
    assert first["domain"] == "sshd"
    assert second["rule_key"] == "sysctl_something"
    assert second["fail_count"] == 1


@pytest.mark.asyncio
async def test_top_violations_surfaces_recent_drift_severity_first(
    client: AsyncClient, db_session: AsyncSession
):
    await _clean(db_session)
    agent_id = uuid.uuid4()
    db_session.add(_agent(agent_id))
    await db_session.commit()

    now = datetime.now(timezone.utc)
    base_id = uuid.uuid4()
    db_session.add(
        DriftEvent(
            time=now,
            agent_id=agent_id,
            id=base_id,
            domain="sshd",
            compared_against="BASELINE",
            severity="HIGH",
            change_type="CONFIG_MODIFIED",
            summary="sshd/PermitRootLogin drifted",
        )
    )
    db_session.add(
        DriftEvent(
            time=now + timedelta(minutes=1),
            agent_id=agent_id,
            id=uuid.uuid4(),
            domain="sshd",
            compared_against="PREVIOUS_SNAPSHOT",
            severity="LOW",
            change_type="CONFIG_MODIFIED",
            summary="older but louder",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/dashboard/top-violations")
    assert resp.status_code == 200
    drift = resp.json()["recent_drift"]

    assert len(drift) == 2
    assert drift[0]["severity"] == "HIGH"  # severity ranks before recency
    assert drift[0]["compared_against"] == "BASELINE"
    assert drift[1]["severity"] == "LOW"


@pytest.mark.asyncio
async def test_top_violations_empty_fleet_returns_empty_widgets(
    client: AsyncClient,
):
    resp = await client.get("/api/v1/compliance/dashboard/top-violations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["top_rules"] == []
    assert body["recent_drift"] == []


@pytest.mark.asyncio
async def test_top_changed_files_ranks_by_frequency(
    client: AsyncClient, db_session: AsyncSession
):
    await _clean(db_session)
    agent_id = uuid.uuid4()
    db_session.add(_agent(agent_id))
    await db_session.commit()

    now = datetime.now(timezone.utc)
    for i in range(4):
        db_session.add(
            FileChange(
                time=now + timedelta(minutes=i),
                agent_id=agent_id,
                path="/etc/ssh/sshd_config",
                old_hash=f"old{i}",
                new_hash=f"new{i}",
                change_kind="MODIFIED",
            )
        )
    db_session.add(
        FileChange(
            time=now + timedelta(minutes=5),
            agent_id=agent_id,
            path="/etc/hosts",
            old_hash="old",
            new_hash="new",
            change_kind="MODIFIED",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/dashboard/top-changed-files")
    assert resp.status_code == 200
    files = resp.json()

    assert files[0]["path"] == "/etc/ssh/sshd_config"
    assert files[0]["change_count"] == 4
    assert files[1]["path"] == "/etc/hosts"
    assert files[1]["change_count"] == 1


@pytest.mark.asyncio
async def test_overview_empty_fleet_reports_full_remediation(client: AsyncClient):
    resp = await client.get("/api/v1/compliance/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_compliance_pct"] == 0.0
    # nothing failing means nothing left to remediate
    assert body["remediation_pct"] == 100.0
    assert body["resolved_controls"] == 0


@pytest.mark.asyncio
async def test_overview_remediation_pct_counts_completed_plans_for_failing_rules(
    client: AsyncClient, db_session: AsyncSession
):
    await _clean(db_session)
    agent_id = uuid.uuid4()
    fixed_rule = ComplianceRule(
        id=uuid.uuid4(), rule_key="fixed_rule", title="Fixed rule", severity="HIGH",
        domain="sshd", check_source="CEL", check_expr="true",
    )
    unfixed_rule = ComplianceRule(
        id=uuid.uuid4(), rule_key="unfixed_rule", title="Unfixed rule", severity="CRITICAL",
        domain="sysctl", check_source="CEL", check_expr="true",
    )
    db_session.add_all([_agent(agent_id), fixed_rule, unfixed_rule])
    await db_session.commit()

    now = datetime.now(timezone.utc)
    policy_set_id = uuid.uuid4()
    db_session.add_all([
        RuleEvaluation(time=now, agent_id=agent_id, rule_id=fixed_rule.id,
                        policy_set_id=policy_set_id, result="FAIL"),
        RuleEvaluation(time=now, agent_id=agent_id, rule_id=unfixed_rule.id,
                        policy_set_id=policy_set_id, result="FAIL"),
    ])

    plan = RemediationPlan(
        id=uuid.uuid4(), name="fix sshd", status="COMPLETED", trigger_type="MANUAL",
    )
    db_session.add(plan)
    await db_session.commit()
    db_session.add(
        RemediationAction(
            id=uuid.uuid4(), remediation_plan_id=plan.id, rule_id=fixed_rule.id,
            agent_id=agent_id, provider="ansible", rendered_body="- name: fix",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_controls"] == 1
    assert body["remediation_pct"] == 50.0
