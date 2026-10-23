import uuid
from datetime import datetime, timedelta, timezone

import pytest

from lokilinux.incidents.models import Incident, IncidentTimeline
from lokilinux.schemas.common import encode_cursor


@pytest.mark.asyncio
async def test_malformed_cursor_is_400_not_500(client):
    bad_cursors = (
        "garbage", "2026-01-01T00:00:00+00:00:not-a-uuid", "not-a-date:" + str(uuid.uuid4())
    )
    for bad in bad_cursors:
        resp = await client.get("/api/v1/incidents", params={"cursor": encode_cursor(bad)})
        assert resp.status_code == 400, bad


@pytest.mark.asyncio
async def test_timeline_is_bounded_by_limit(client, db_session):
    incident = Incident(
        tenant_id="default", title="t", type="application_degradation", severity="HIGH",
        status="OPEN", group_key=str(uuid.uuid4()),
    )
    db_session.add(incident)
    await db_session.flush()
    base = datetime.now(timezone.utc)
    for i in range(3):  # explicit ts: now() is the transaction start, identical for all three
        db_session.add(IncidentTimeline(
            incident_id=incident.id, kind="note", message=f"n{i}", ts=base + timedelta(seconds=i)
        ))
    await db_session.commit()

    url = f"/api/v1/incidents/{incident.id}/timeline"
    page1 = (await client.get(url, params={"limit": 2})).json()
    assert [t["message"] for t in page1["items"]] == ["n0", "n1"]
    assert page1["next_cursor"]

    page2 = (await client.get(url, params={"limit": 2, "cursor": page1["next_cursor"]})).json()
    assert [t["message"] for t in page2["items"]] == ["n2"]  # no overlap, nothing skipped
    assert page2["next_cursor"] is None

    assert (await client.get(url, params={"limit": 0})).status_code == 422
    assert (await client.get(url, params={"cursor": "garbage"})).status_code == 400
