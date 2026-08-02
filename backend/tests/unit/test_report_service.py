"""Unit/integration tests for report_service.py's data builder — real
Postgres via the shared db_session fixture (conftest.py), not mocks."""

import uuid
from datetime import datetime, timezone

import pytest

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.compliance_rule import ComplianceRule, PolicySet, PolicySetRule
from lokilinux.models.rule_evaluation import RuleEvaluation
from lokilinux.services.report_service import (
    build_fleet_summary_data,
    to_csv,
    to_json,
    to_pdf,
    to_xlsx,
)


async def _seed_rule_and_evaluation(
    db_session, *, domain: str, result: str, agent_id
) -> ComplianceRule:
    rule = ComplianceRule(
        rule_key=f"rule-{uuid.uuid4()}",
        title=f"Test rule for {domain}",
        severity="HIGH",
        domain=domain,
        check_source="CEL",
    )
    db_session.add(rule)
    await db_session.flush()

    db_session.add(
        RuleEvaluation(
            time=datetime.now(timezone.utc),
            agent_id=agent_id,
            rule_id=rule.id,
            # rule_evaluations.policy_set_id doesn't gate report scoping —
            # policy_set_rules does, so any UUID here is fine.
            policy_set_id=uuid.uuid4(),
            result=result,
        )
    )
    return rule


@pytest.mark.asyncio
async def test_build_fleet_summary_data_no_filter_includes_everything(db_session):
    agent = Agent(agent_id=f"agent-{uuid.uuid4()}", status=AgentStatus.ACTIVE, hostname="h1")
    db_session.add(agent)
    await db_session.flush()

    await _seed_rule_and_evaluation(db_session, domain="sshd", result="PASS", agent_id=agent.id)
    await _seed_rule_and_evaluation(db_session, domain="sysctl", result="PASS", agent_id=agent.id)
    await db_session.commit()

    data = await build_fleet_summary_data(db_session, agent_id=agent.id)

    assert "security" in data["categories"]
    assert "configuration" in data["categories"]
    assert data["total_rules_evaluated"] == 2


@pytest.mark.asyncio
async def test_build_fleet_summary_data_policy_set_filter_excludes_other_rules(db_session):
    agent = Agent(agent_id=f"agent-{uuid.uuid4()}", status=AgentStatus.ACTIVE, hostname="h2")
    db_session.add(agent)
    await db_session.flush()

    in_scope_rule = await _seed_rule_and_evaluation(
        db_session, domain="sshd", result="FAIL", agent_id=agent.id
    )
    await _seed_rule_and_evaluation(db_session, domain="sysctl", result="PASS", agent_id=agent.id)
    await db_session.flush()

    policy_set = PolicySet(name="Scoped Set", slug=f"scoped-{uuid.uuid4()}", framework="INTERNAL")
    db_session.add(policy_set)
    await db_session.flush()
    db_session.add(PolicySetRule(policy_set_id=policy_set.id, rule_id=in_scope_rule.id))
    await db_session.commit()

    data = await build_fleet_summary_data(
        db_session, agent_id=agent.id, policy_set_id=policy_set.id
    )

    # Only the sshd rule belongs to the policy set — sysctl (configuration)
    # must not leak into a POLICY_SET-scoped report.
    assert data["total_rules_evaluated"] == 1
    assert "security" in data["categories"]
    assert "configuration" not in data["categories"]
    assert data["categories"]["security"]["failed"] == 1


_SAMPLE_REPORT_DATA = {
    "generated_at": "2026-01-01T00:00:00",
    "overall_score": 87.5,
    "categories": {"security": {"passed": 7, "failed": 1, "score": 87.5}},
    "top_violations": [
        {
            "agent_id": "a1",
            "domain": "sshd",
            "severity": "HIGH",
            "title": "Root login enabled",
            "time": "2026-01-01T00:00:00",
        }
    ],
    "total_rules_evaluated": 8,
}


def test_to_json_round_trips():
    import json

    parsed = json.loads(to_json(_SAMPLE_REPORT_DATA))
    assert parsed["overall_score"] == 87.5
    assert parsed["categories"]["security"]["failed"] == 1


def test_to_csv_contains_category_and_violation_rows():
    text = to_csv(_SAMPLE_REPORT_DATA).decode("utf-8")
    assert "security" in text
    assert "Root login enabled" in text


def test_to_xlsx_produces_a_real_xlsx_file():
    body = to_xlsx(_SAMPLE_REPORT_DATA)
    # XLSX is a zip archive — "PK\x03\x04" is the zip local-file-header
    # signature, the cheapest real check that this isn't garbage bytes.
    assert body[:4] == b"PK\x03\x04"
    assert len(body) > 100


def test_to_pdf_produces_a_real_pdf_file():
    body = to_pdf(_SAMPLE_REPORT_DATA)
    assert body[:5] == b"%PDF-"
    assert len(body) > 500


def test_to_pdf_handles_no_violations():
    data = {**_SAMPLE_REPORT_DATA, "top_violations": []}
    body = to_pdf(data)
    assert body[:5] == b"%PDF-"
