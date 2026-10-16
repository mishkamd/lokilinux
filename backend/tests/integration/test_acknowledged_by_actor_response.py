"""MIS-8 finishing: acknowledged_by_actor is part of the alert, drift and finding
responses, and approve_step refuses to run without an explicit actor_id.

Each test fails on the pre-fix code for the reason named in its docstring.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from lokilinux.models.agent import Agent
from lokilinux.models.alert import Alert
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.drift import DriftEvent
from lokilinux.models.rule_evaluation import RuleEvaluation
from lokilinux.services.workflow_engine import approve_step

NANOID = "k3Xq9wLbz0nanoidA"


def _agent(agent_id: uuid.UUID) -> Agent:
    return Agent(
        id=agent_id, agent_id=str(agent_id), hostname=f"host-{agent_id.hex[:8]}",
        os_distro="ol", os_version="9",
    )


def _rule(rule_id: uuid.UUID) -> ComplianceRule:
    return ComplianceRule(
        id=rule_id, rule_key=f"rule-{rule_id}", title="Disable SSH root login",
        severity="HIGH", domain="sshd", check_source="CEL", check_expr="true",
    )


@pytest.mark.asyncio
async def test_alert_list_carries_acknowledged_by_actor(
    client: AsyncClient, db_session, current_user
):
    """AlertResponse had no acknowledged_by_actor, so the nanoid acknowledger was
    invisible in the alert list even though the column was set (MIS-8)."""
    current_user["id"] = NANOID
    alert = Alert(title="a1", severity="HIGH", alert_type="AGENT_OFFLINE", status="ACTIVE")
    db_session.add(alert)
    await db_session.commit()

    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge")
    assert resp.status_code == 200, resp.text

    listed = await client.get("/api/v1/alerts")
    items = {item["id"]: item for item in listed.json()["items"]}
    assert items[str(alert.id)]["acknowledged_by_actor"] == NANOID


@pytest.mark.asyncio
async def test_drift_acknowledge_response_carries_acknowledged_by_actor(
    client: AsyncClient, db_session, current_user
):
    """DriftEventResponse had no acknowledged_by_actor field, so the acknowledge response
    dropped the nanoid actor the row itself kept (MIS-8)."""
    current_user["id"] = NANOID
    agent_id, drift_id = uuid.uuid4(), uuid.uuid4()
    db_session.add(_agent(agent_id))
    await db_session.commit()
    db_session.add(DriftEvent(
        time=datetime.now(timezone.utc), agent_id=agent_id, id=drift_id, domain="sshd",
        compared_against="BASELINE", severity="HIGH", change_type="MODIFIED",
        summary="sshd config drifted", status="OPEN",
    ))
    await db_session.commit()

    resp = await client.post(f"/api/v1/compliance/drift-events/{drift_id}/acknowledge")
    assert resp.status_code == 200, resp.text
    assert resp.json()["acknowledged_by_actor"] == NANOID


@pytest.mark.asyncio
async def test_finding_acknowledgement_carries_acknowledged_by_actor_in_detail_and_list(
    client: AsyncClient, db_session, current_user
):
    """FindingResponse had no acknowledged_by_actor, and both the list (_to_response over
    _FINDING_COLS) and the acknowledge/detail response (get_finding) built it without the
    column, so the nanoid acknowledger was dropped (MIS-8)."""
    current_user["id"] = NANOID
    agent_id, rule_id = uuid.uuid4(), uuid.uuid4()
    db_session.add_all([_agent(agent_id), _rule(rule_id)])
    await db_session.commit()
    db_session.add(RuleEvaluation(
        time=datetime.now(timezone.utc), agent_id=agent_id, rule_id=rule_id,
        policy_set_id=uuid.uuid4(), result="FAIL", actual_value={}, evidence={},
        expected_value={}, evidence_hash="deadbeef", source="lokilinux-agent",
    ))
    await db_session.commit()

    listed = await client.get("/api/v1/compliance/findings", params={"agent_id": str(agent_id)})
    finding_id = listed.json()["items"][0]["id"]
    resp = await client.post(f"/api/v1/compliance/findings/{finding_id}/acknowledge")
    assert resp.status_code == 200, resp.text
    assert resp.json()["acknowledged_by_actor"] == NANOID

    listed = await client.get("/api/v1/compliance/findings", params={"agent_id": str(agent_id)})
    assert listed.json()["items"][0]["acknowledged_by_actor"] == NANOID


def test_approve_step_requires_actor_id():
    """approve_step had actor_id defaulting to None, so a non-HTTP caller could skip the
    publisher check by omitting it. Calling without actor_id must raise TypeError."""
    with pytest.raises(TypeError, match="actor_id"):
        approve_step(None, None, None, uuid.uuid4(), "gate", actor=None)
