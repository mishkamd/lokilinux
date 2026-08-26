import pytest

from lokilinux.signals.models import CorrelationRule


async def _make_rule(db_session, name: str = "test-rule") -> CorrelationRule:
    rule = CorrelationRule(
        tenant_id="default", name=name, enabled=True, window_seconds=300,
        group_by=["host_id"], conditions=[{"signal": "cpu.high", "weight": 60}],
        threshold_score=60, incident_type="application_degradation", incident_severity="CRITICAL",
    )
    db_session.add(rule)
    await db_session.flush()
    await db_session.commit()
    return rule


@pytest.mark.asyncio
async def test_list_rules_empty(client):
    resp = await client.get("/api/v1/correlation/rules")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_rule(client):
    resp = await client.post("/api/v1/correlation/rules", json={
        "name": "app-degradation", "window_seconds": 300, "group_by": ["host_id"],
        "conditions": [{"signal": "cpu.high", "weight": 60}], "threshold_score": 60,
        "incident_type": "application_degradation", "incident_severity": "CRITICAL",
    })
    assert resp.status_code == 201
    assert resp.json()["name"] == "app-degradation"


@pytest.mark.asyncio
async def test_create_rule_rejects_window_out_of_range(client):
    resp = await client.post("/api/v1/correlation/rules", json={
        "name": "bad-window", "window_seconds": 10, "group_by": ["host_id"],
        "conditions": [{"signal": "cpu.high", "weight": 60}], "threshold_score": 60,
        "incident_type": "application_degradation", "incident_severity": "CRITICAL",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rule_rejects_zero_weight_condition(client):
    resp = await client.post("/api/v1/correlation/rules", json={
        "name": "bad-weight", "window_seconds": 300, "group_by": ["host_id"],
        "conditions": [{"signal": "cpu.high", "weight": 0}], "threshold_score": 60,
        "incident_type": "application_degradation", "incident_severity": "CRITICAL",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_and_delete_rule(client, db_session):
    rule = await _make_rule(db_session)

    update_resp = await client.patch(f"/api/v1/correlation/rules/{rule.id}", json={
        "name": "test-rule", "window_seconds": 300, "group_by": ["host_id"],
        "conditions": [{"signal": "cpu.high", "weight": 60}], "threshold_score": 80,
        "incident_type": "application_degradation", "incident_severity": "CRITICAL",
    })
    assert update_resp.status_code == 200
    assert update_resp.json()["threshold_score"] == 80
    assert update_resp.json()["version"] == 2  # bumped on update

    delete_resp = await client.delete(f"/api/v1/correlation/rules/{rule.id}")
    assert delete_resp.status_code == 204

    listing = await client.get("/api/v1/correlation/rules")
    assert listing.json() == []
