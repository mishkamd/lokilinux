from datetime import datetime, timezone
from uuid import uuid4

import pytest

from lokilinux.events.fingerprint import fingerprint
from lokilinux.incidents.models import Incident, IncidentSignal, IncidentTimeline
from lokilinux.signals.models import Signal


async def _make_incident_with_signal(db_session) -> tuple[Incident, Signal]:
    now = datetime.now(timezone.utc)
    sig = Signal(
        tenant_id="default", type="cpu.high", severity="HIGH", status="OPEN",
        fingerprint=fingerprint("default", "host-1", "cpu.high", None),
        first_seen=now, last_seen=now,
    )
    db_session.add(sig)
    await db_session.flush()

    incident = Incident(
        tenant_id="default", title="CPU degraded on host-1", type="application_degradation",
        severity="CRITICAL", status="OPEN", group_key=str(uuid4()),
    )
    db_session.add(incident)
    await db_session.flush()
    db_session.add(IncidentSignal(incident_id=incident.id, signal_id=sig.id))
    db_session.add(IncidentTimeline(incident_id=incident.id, kind="created", message="opened"))
    await db_session.flush()
    await db_session.commit()
    return incident, sig


@pytest.mark.asyncio
async def test_list_incidents_empty(client):
    resp = await client.get("/api/v1/incidents")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_list_incidents_returns_created_row(client, db_session):
    incident, _ = await _make_incident_with_signal(db_session)
    resp = await client.get("/api/v1/incidents")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(incident.id)


@pytest.mark.asyncio
async def test_list_incidents_reports_total_and_search(client, db_session):
    incident, _ = await _make_incident_with_signal(db_session)
    resp = await client.get("/api/v1/incidents")
    assert resp.status_code == 200
    # The badge in the UI must count the whole filtered set, not the page.
    assert resp.json()["total"] == 1

    hit = await client.get("/api/v1/incidents", params={"search": "degraded"})
    assert hit.status_code == 200
    assert hit.json()["total"] == 1
    assert hit.json()["items"][0]["id"] == str(incident.id)

    miss = await client.get("/api/v1/incidents", params={"search": "nothing-matches"})
    assert miss.json()["items"] == []
    assert miss.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_incidents_search_matches_the_hostname(client, db_session):
    """The Host column shows a hostname, so the search box has to find it."""
    from lokilinux.models.agent import Agent, AgentStatus

    agent = Agent(agent_id=str(uuid4()), status=AgentStatus.ACTIVE, hostname="rocky")
    db_session.add(agent)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    sig = Signal(
        tenant_id="default", type="host.unreachable", severity="CRITICAL", status="OPEN",
        host_id=agent.id,
        fingerprint=fingerprint("default", str(agent.id), "host.unreachable", None),
        first_seen=now, last_seen=now,
    )
    db_session.add(sig)
    await db_session.flush()
    incident = Incident(
        tenant_id="default", title="Host Down", type="host_down",
        severity="CRITICAL", status="OPEN", group_key=str(uuid4()),
        root_cause_signal_id=sig.id,
    )
    db_session.add(incident)
    await db_session.flush()
    await db_session.commit()

    resp = await client.get("/api/v1/incidents", params={"search": "rocky"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(incident.id)
    assert body["items"][0]["hostname"] == "rocky"


@pytest.mark.asyncio
async def test_filter_by_status(client, db_session):
    await _make_incident_with_signal(db_session)
    resp = await client.get("/api/v1/incidents", params={"status": "RESOLVED"})
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_get_incident_detail_includes_signals_and_timeline(client, db_session):
    incident, sig = await _make_incident_with_signal(db_session)
    resp = await client.get(f"/api/v1/incidents/{incident.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(incident.id)
    assert [s["id"] for s in body["signals"]] == [str(sig.id)]
    assert any(t["kind"] == "created" for t in body["timeline"])


@pytest.mark.asyncio
async def test_get_incident_404_for_unknown_id(client):
    resp = await client.get(f"/api/v1/incidents/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_timeline(client, db_session):
    incident, _ = await _make_incident_with_signal(db_session)
    resp = await client.get(f"/api/v1/incidents/{incident.id}/timeline")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_get_evidence(client, db_session, fake_ch):
    incident, _ = await _make_incident_with_signal(db_session)
    fake_ch.queued_columns = ["timestamp", "tenant", "incident_id", "kind", "ref", "summary"]
    fake_ch.queued_rows = [[datetime.now(timezone.utc), "default", str(incident.id), "signal", "fp123", "cpu.high"]]

    resp = await client.get(f"/api/v1/incidents/{incident.id}/evidence")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


@pytest.mark.asyncio
async def test_ack_resolve_reopen_flow(client, db_session):
    incident, _ = await _make_incident_with_signal(db_session)

    ack_resp = await client.post(f"/api/v1/incidents/{incident.id}/ack")
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "ACKNOWLEDGED"

    resolve_resp = await client.post(f"/api/v1/incidents/{incident.id}/resolve")
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "RESOLVED"

    reopen_resp = await client.post(f"/api/v1/incidents/{incident.id}/reopen")
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["status"] == "OPEN"


@pytest.mark.asyncio
async def test_illegal_transition_returns_409(client, db_session):
    incident, _ = await _make_incident_with_signal(db_session)
    resp = await client.post(f"/api/v1/incidents/{incident.id}/reopen")  # OPEN -> OPEN isn't legal
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_ack_unknown_incident_404s(client):
    resp = await client.post(f"/api/v1/incidents/{uuid4()}/ack")
    assert resp.status_code == 404
