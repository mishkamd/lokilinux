"""
Incidents carry the hostname of the agent they belong to.

Owning agent = root-cause signal's host_id (a signals.host_id is the agents.id
of the reporting host, see api/grpc/agent_service.py host_id=str(agent.id)).
"""

import uuid
from datetime import datetime, timezone

import pytest

from lokilinux.events.fingerprint import fingerprint
from lokilinux.incidents.models import Incident, IncidentSignal
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.signals.models import Signal


async def _make_agent(db_session, hostname: str) -> Agent:
    agent = Agent(agent_id=str(uuid.uuid4()), status=AgentStatus.ACTIVE, hostname=hostname)
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _make_incident(db_session, host_id: uuid.UUID | None) -> Incident:
    now = datetime.now(timezone.utc)
    incident = Incident(
        tenant_id="default",
        title="CPU degraded",
        type="application_degradation",
        severity="CRITICAL",
        status="OPEN",
        group_key=str(uuid.uuid4()),
    )
    db_session.add(incident)
    await db_session.flush()
    if host_id is not None:
        sig = Signal(
            tenant_id="default",
            type="cpu.high",
            severity="HIGH",
            status="OPEN",
            host_id=host_id,
            fingerprint=fingerprint("default", str(host_id), "cpu.high", None),
            first_seen=now,
            last_seen=now,
        )
        db_session.add(sig)
        await db_session.flush()
        incident.root_cause_signal_id = sig.id
        db_session.add(IncidentSignal(incident_id=incident.id, signal_id=sig.id))
        await db_session.flush()
    await db_session.commit()
    return incident


@pytest.mark.asyncio
async def test_list_items_carry_hostname_of_owning_agent(client, db_session):
    web = await _make_agent(db_session, "web-01")
    db = await _make_agent(db_session, "db-01")
    inc_web = await _make_incident(db_session, web.id)
    inc_db = await _make_incident(db_session, db.id)
    inc_fleet = await _make_incident(db_session, None)  # no agent behind it

    resp = await client.get("/api/v1/incidents")
    assert resp.status_code == 200
    items = {item["id"]: item for item in resp.json()["items"]}
    assert len(items) == 3

    expected = {str(inc_web.id): "web-01", str(inc_db.id): "db-01", str(inc_fleet.id): None}
    for incident_id, hostname in expected.items():
        assert "hostname" in items[incident_id], "incident list item carries no hostname"
        assert items[incident_id]["hostname"] == hostname


@pytest.mark.asyncio
async def test_detail_and_ack_carry_hostname(client, db_session):
    agent = await _make_agent(db_session, "web-01")
    incident = await _make_incident(db_session, agent.id)

    detail = await client.get(f"/api/v1/incidents/{incident.id}")
    assert detail.status_code == 200
    assert "hostname" in detail.json(), "incident detail carries no hostname"
    assert detail.json()["hostname"] == "web-01"

    ack = await client.post(f"/api/v1/incidents/{incident.id}/ack")
    assert ack.status_code == 200
    assert "hostname" in ack.json(), "ack response carries no hostname"
    assert ack.json()["hostname"] == "web-01"
