"""
An incident of another tenant is 404 by id, not only missing from the list.
"""

import uuid

import pytest

from lokilinux.incidents.models import Incident


async def _make_incident(db_session, tenant_id: str) -> Incident:
    incident = Incident(
        tenant_id=tenant_id,
        title="CPU degraded",
        type="application_degradation",
        severity="CRITICAL",
        status="OPEN",
        group_key=str(uuid.uuid4()),
    )
    db_session.add(incident)
    await db_session.commit()
    return incident


@pytest.mark.asyncio
async def test_foreign_tenant_incident_is_404_on_read_and_transition(client, db_session):
    foreign = await _make_incident(db_session, "other")

    assert (await client.get(f"/api/v1/incidents/{foreign.id}")).status_code == 404
    assert (await client.get(f"/api/v1/incidents/{foreign.id}/timeline")).status_code == 404
    assert (await client.post(f"/api/v1/incidents/{foreign.id}/ack")).status_code == 404
