"""MIS-8 family: drift and compliance-finding acknowledgements keep the raw auth id.

Better Auth ids are nanoids that never parse as UUID, so acknowledged_by (UUID) was
NULL for them and the acknowledgement recorded no actor. The raw id is kept in
acknowledged_by_actor on both tables.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.agent import Agent
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.drift import DriftEvent
from lokilinux.models.rule_evaluation import RuleEvaluation

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
async def test_nanoid_finding_acknowledgement_keeps_the_raw_id(
    client: AsyncClient, db_session, current_user
):
    current_user["id"] = NANOID
    agent_id, rule_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    db_session.add_all([_agent(agent_id), _rule(rule_id)])
    await db_session.commit()
    db_session.add(RuleEvaluation(
        time=now, agent_id=agent_id, rule_id=rule_id, policy_set_id=uuid.uuid4(),
        result="FAIL", actual_value={}, evidence={}, expected_value={},
        evidence_hash="deadbeef", source="lokilinux-agent",
    ))
    await db_session.commit()

    listed = await client.get("/api/v1/compliance/findings", params={"agent_id": str(agent_id)})
    finding_id = listed.json()["items"][0]["id"]
    resp = await client.post(f"/api/v1/compliance/findings/{finding_id}/acknowledge")
    assert resp.status_code == 200, resp.text

    row = (
        await db_session.execute(select(RuleEvaluation).where(RuleEvaluation.agent_id == agent_id))
    ).scalar_one()
    await db_session.refresh(row)
    assert row.acknowledged_by_actor == NANOID


@pytest.mark.asyncio
async def test_nanoid_drift_acknowledgement_keeps_the_raw_id(
    client: AsyncClient, db_session, current_user
):
    current_user["id"] = NANOID
    agent_id, drift_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    db_session.add(_agent(agent_id))
    await db_session.commit()
    db_session.add(DriftEvent(
        time=now, agent_id=agent_id, id=drift_id, domain="sshd", compared_against="BASELINE",
        severity="HIGH", change_type="MODIFIED", summary="sshd config drifted", status="OPEN",
    ))
    await db_session.commit()

    resp = await client.post(f"/api/v1/compliance/drift-events/{drift_id}/acknowledge")
    assert resp.status_code == 200, resp.text

    row = (
        await db_session.execute(select(DriftEvent).where(DriftEvent.id == drift_id))
    ).scalar_one()
    await db_session.refresh(row)
    assert row.acknowledged_by_actor == NANOID
