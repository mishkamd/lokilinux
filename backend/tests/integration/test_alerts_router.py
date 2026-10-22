"""Integration tests for /api/v1/alerts.

Regression coverage: list_alerts used to return raw Alert ORM instances
through a handler annotated `-> dict`, which pydantic-core cannot serialize —
every non-empty response was a 500, confirmed live. These tests would have
caught it.
"""

import pytest
from httpx import AsyncClient

from lokilinux.models.alert import Alert, AlertRule


@pytest.mark.asyncio
async def test_list_alerts_returns_200_with_data(client: AsyncClient, db_session):
    db_session.add(Alert(title="Agent X UNHEALTHY", severity="HIGH", alert_type="AGENT_OFFLINE", status="ACTIVE"))
    await db_session.commit()

    resp = await client.get("/api/v1/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Agent X UNHEALTHY"
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_list_alerts_filters_by_status(client: AsyncClient, db_session):
    db_session.add(Alert(title="a1", severity="HIGH", alert_type="AGENT_OFFLINE", status="ACTIVE"))
    db_session.add(Alert(title="a2", severity="HIGH", alert_type="AGENT_OFFLINE", status="RESOLVED"))
    await db_session.commit()

    resp = await client.get("/api/v1/alerts", params={"status": "active"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "a1"


@pytest.mark.asyncio
async def test_list_alerts_filters_by_search(client: AsyncClient, db_session):
    db_session.add(
        Alert(
            title="Agent X UNHEALTHY",
            severity="HIGH",
            alert_type="AGENT_OFFLINE",
            status="ACTIVE",
        )
    )
    db_session.add(
        Alert(
            title="Agent Y UNHEALTHY",
            severity="HIGH",
            alert_type="AGENT_OFFLINE",
            status="ACTIVE",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/alerts", params={"search": "Agent X"})
    assert resp.status_code == 200
    body = resp.json()
    assert [i["title"] for i in body["items"]] == ["Agent X UNHEALTHY"]
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_list_alerts_paginates_with_a_cursor(client: AsyncClient, db_session):
    """The oldest alerts must be reachable — the list used to be capped at
    the newest N with no way to ask for more."""
    for i in range(3):
        db_session.add(
            Alert(title=f"alert-{i}", severity="HIGH", alert_type="AGENT_OFFLINE", status="ACTIVE")
        )
    await db_session.commit()

    first = await client.get("/api/v1/alerts", params={"limit": 2})
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["next_cursor"]

    second = await client.get(
        "/api/v1/alerts", params={"limit": 2, "cursor": body["next_cursor"]}
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["items"][0]["title"] not in {i["title"] for i in body["items"]}


@pytest.mark.asyncio
async def test_list_alert_rules_returns_200_with_data(client: AsyncClient, db_session):
    db_session.add(AlertRule(name="rule-1", conditions={}, is_enabled=True))
    await db_session.commit()

    resp = await client.get("/api/v1/alerts/rules")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


@pytest.mark.asyncio
async def test_nanoid_user_acknowledgement_keeps_the_raw_id(
    client: AsyncClient, db_session, current_user
):
    """Better Auth ids are nanoids that never parse as UUID. The UUID column cannot
    hold them, and the acknowledgement used to skip the actor entirely (MIS-8). The
    raw id must be kept beside it."""
    current_user["id"] = "k3Xq9wLbz0nanoidA"
    alert = Alert(title="a1", severity="HIGH", alert_type="AGENT_OFFLINE", status="ACTIVE")
    db_session.add(alert)
    await db_session.commit()

    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACKNOWLEDGED"

    await db_session.refresh(alert)
    assert alert.acknowledged_by_actor == "k3Xq9wLbz0nanoidA"


@pytest.mark.asyncio
async def test_acknowledge_and_resolve_alert(client: AsyncClient, db_session):
    alert = Alert(title="a1", severity="HIGH", alert_type="AGENT_OFFLINE", status="ACTIVE")
    db_session.add(alert)
    await db_session.commit()

    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACKNOWLEDGED"

    resp = await client.post(f"/api/v1/alerts/{alert.id}/resolve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "RESOLVED"
