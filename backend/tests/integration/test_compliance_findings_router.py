"""Integration tests for /api/v1/compliance/findings (Enterprise Compliance
plan U4) — the read-model over rule_evaluations, deduplicated to the latest
verdict per (agent_id, rule_id)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.agent import Agent
from lokilinux.models.audit import AuditLog
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.drift import DriftEvent
from lokilinux.models.inventory import InventoryBlob, InventorySnapshot
from lokilinux.models.rule_evaluation import RuleEvaluation


def _agent(agent_id: uuid.UUID, hostname: str) -> Agent:
    return Agent(
        id=agent_id, agent_id=str(agent_id), hostname=hostname, os_distro="ol", os_version="9"
    )


def _rule(rule_id: uuid.UUID, severity: str = "HIGH", domain: str = "sshd") -> ComplianceRule:
    return ComplianceRule(
        id=rule_id,
        rule_key=f"rule-{rule_id}",
        title="Disable SSH root login",
        severity=severity,
        domain=domain,
        check_source="CEL",
        check_expr="true",
    )


def _evaluation(
    agent_id: uuid.UUID,
    rule_id: uuid.UUID,
    time: datetime,
    result: str = "FAIL",
    policy_set_id: uuid.UUID | None = None,
) -> RuleEvaluation:
    return RuleEvaluation(
        time=time,
        agent_id=agent_id,
        rule_id=rule_id,
        policy_set_id=policy_set_id or uuid.uuid4(),
        result=result,
        actual_value={"PermitRootLogin": "yes"},
        evidence={"fact_paths": ["sshd.PermitRootLogin"]},
        expected_value={"PermitRootLogin": "no"},
        evidence_hash="deadbeef",
        source="lokilinux-agent",
    )


@pytest.mark.asyncio
async def test_list_findings_dedups_to_latest_and_defaults_to_fail(
    client: AsyncClient, db_session: AsyncSession
):
    agent_id = uuid.uuid4()
    rule_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db_session.add_all([_agent(agent_id, "web-1"), _rule(rule_id)])
    await db_session.commit()

    # Older FAIL, then a newer PASS — the latest verdict is PASS, so with
    # the default result=FAIL filter this rule must NOT appear.
    db_session.add(_evaluation(agent_id, rule_id, now - timedelta(minutes=5), result="FAIL"))
    db_session.add(_evaluation(agent_id, rule_id, now, result="PASS"))
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/findings")
    assert resp.status_code == 200
    body = resp.json()
    assert all(item["rule_id"] != str(rule_id) for item in body["items"])

    resp_all = await client.get("/api/v1/compliance/findings", params={"result": ""})
    assert resp_all.status_code == 200
    matches = [i for i in resp_all.json()["items"] if i["rule_id"] == str(rule_id)]
    assert len(matches) == 1
    assert matches[0]["result"] == "PASS"
    assert matches[0]["hostname"] == "web-1"


@pytest.mark.asyncio
async def test_list_findings_filters_by_severity_and_domain(
    client: AsyncClient, db_session: AsyncSession
):
    agent_id = uuid.uuid4()
    high_rule = uuid.uuid4()
    low_rule = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            _agent(agent_id, "web-2"),
            _rule(high_rule, severity="CRITICAL", domain="sshd"),
            _rule(low_rule, severity="LOW", domain="sysctl"),
        ]
    )
    await db_session.commit()
    db_session.add_all(
        [
            _evaluation(agent_id, high_rule, now, result="FAIL"),
            _evaluation(agent_id, low_rule, now, result="FAIL"),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/findings", params={"severity": "CRITICAL"})
    body = resp.json()
    assert {i["rule_id"] for i in body["items"]} == {str(high_rule)}

    resp = await client.get("/api/v1/compliance/findings", params={"domain": "sysctl"})
    body = resp.json()
    assert {i["rule_id"] for i in body["items"]} == {str(low_rule)}


@pytest.mark.asyncio
async def test_get_finding_detail_includes_snapshot_and_open_drift(
    client: AsyncClient, db_session: AsyncSession
):
    agent_id = uuid.uuid4()
    rule_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db_session.add_all([_agent(agent_id, "web-3"), _rule(rule_id, domain="sshd")])
    await db_session.commit()

    blob = InventoryBlob(content_hash="a" * 64, body=b"{}", size_bytes=2)
    db_session.add(blob)
    await db_session.commit()
    snapshot = InventorySnapshot(
        agent_id=agent_id, domain="sshd", content_hash="a" * 64, taken_at=now - timedelta(minutes=1)
    )
    drift = DriftEvent(
        time=now,
        agent_id=agent_id,
        id=uuid.uuid4(),
        domain="sshd",
        compared_against="BASELINE",
        severity="HIGH",
        change_type="MODIFIED",
        summary="sshd config drifted",
        status="OPEN",
    )
    db_session.add_all([snapshot, drift])
    evaluation = _evaluation(agent_id, rule_id, now, result="FAIL")
    db_session.add(evaluation)
    await db_session.commit()

    list_resp = await client.get("/api/v1/compliance/findings", params={"agent_id": str(agent_id)})
    finding_id = list_resp.json()["items"][0]["id"]

    resp = await client.get(f"/api/v1/compliance/findings/{finding_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["actual_value"] == {"PermitRootLogin": "yes"}
    assert body["expected_value"] == {"PermitRootLogin": "no"}
    assert body["snapshot_content_hash"] == "a" * 64
    assert body["open_drift_event_id"] == str(drift.id)

    resp_404 = await client.get("/api/v1/compliance/findings/not-a-real-id")
    assert resp_404.status_code in (400, 404)


@pytest.mark.asyncio
async def test_acknowledge_finding_sets_columns_and_audits(
    client: AsyncClient, db_session: AsyncSession
):
    agent_id = uuid.uuid4()
    rule_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db_session.add_all([_agent(agent_id, "web-4"), _rule(rule_id)])
    await db_session.commit()
    db_session.add(_evaluation(agent_id, rule_id, now, result="FAIL"))
    await db_session.commit()

    list_resp = await client.get("/api/v1/compliance/findings", params={"agent_id": str(agent_id)})
    finding_id = list_resp.json()["items"][0]["id"]
    assert list_resp.json()["items"][0]["acknowledged_at"] is None

    resp = await client.post(f"/api/v1/compliance/findings/{finding_id}/acknowledge")
    assert resp.status_code == 200
    body = resp.json()
    assert body["acknowledged_at"] is not None
    assert body["acknowledged_by"] is not None

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "compliance.finding_acknowledged")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].resource_id == finding_id


@pytest.mark.asyncio
async def test_acknowledge_finding_requires_operator_or_admin(
    client: AsyncClient, db_session: AsyncSession, current_user: dict
):
    agent_id = uuid.uuid4()
    rule_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db_session.add_all([_agent(agent_id, "web-5"), _rule(rule_id)])
    await db_session.commit()
    db_session.add(_evaluation(agent_id, rule_id, now, result="FAIL"))
    await db_session.commit()

    list_resp = await client.get("/api/v1/compliance/findings", params={"agent_id": str(agent_id)})
    finding_id = list_resp.json()["items"][0]["id"]

    current_user["role"] = "VIEWER"
    resp = await client.post(f"/api/v1/compliance/findings/{finding_id}/acknowledge")
    assert resp.status_code == 403
