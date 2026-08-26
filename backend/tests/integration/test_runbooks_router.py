import pytest

from lokilinux.models.workflow import Workflow


async def _make_workflow(db_session) -> Workflow:
    from uuid import uuid4

    wf = Workflow(name=f"wf-{uuid4()}", slug=f"wf-{uuid4()}")
    db_session.add(wf)
    await db_session.flush()
    await db_session.commit()
    return wf


@pytest.mark.asyncio
async def test_list_runbooks_empty(client):
    resp = await client.get("/api/v1/runbooks")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_update_delete_runbook(client, db_session):
    wf = await _make_workflow(db_session)

    create_resp = await client.post("/api/v1/runbooks", json={
        "name": "app-degradation", "incident_type": "application_degradation",
        "workflow_id": str(wf.id), "trigger_mode": "MANUAL", "min_severity": "HIGH",
    })
    assert create_resp.status_code == 201
    runbook_id = create_resp.json()["id"]

    update_resp = await client.patch(f"/api/v1/runbooks/{runbook_id}", json={
        "name": "app-degradation", "incident_type": "application_degradation",
        "workflow_id": str(wf.id), "trigger_mode": "AUTO", "min_severity": "CRITICAL",
    })
    assert update_resp.status_code == 200
    assert update_resp.json()["trigger_mode"] == "AUTO"

    delete_resp = await client.delete(f"/api/v1/runbooks/{runbook_id}")
    assert delete_resp.status_code == 204

    listing = await client.get("/api/v1/runbooks")
    assert listing.json() == []


@pytest.mark.asyncio
async def test_execute_nonexistent_runbook_404s(client):
    from uuid import uuid4

    resp = await client.post(f"/api/v1/runbooks/{uuid4()}/execute", json={})
    assert resp.status_code == 404
