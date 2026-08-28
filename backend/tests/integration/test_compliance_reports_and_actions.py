"""Integration tests for the three compliance endpoints that call
safe_user_uuid — regression coverage for a bug where safe_user_uuid(dict)
was called as safe_user_uuid(dict["id"]) (a bare string), which crashes
with AttributeError the moment safe_user_uuid tries current_user.get("id")
on something that isn't a dict. Found via full build verification, not by
any test — these didn't exist before.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from lokilinux.models.drift import DriftEvent


@pytest.mark.asyncio
async def test_acknowledge_drift_event_sets_acknowledged_by(
    client: AsyncClient, db_session, current_user
):
    event = DriftEvent(
        time=datetime.now(timezone.utc),
        agent_id=uuid.uuid4(),
        id=uuid.uuid4(),
        domain="sshd",
        compared_against="PREVIOUS_SNAPSHOT",
        severity="HIGH",
        change_type="CONFIG_MODIFIED",
        summary="sshd: /PermitRootLogin changed",
    )
    db_session.add(event)
    await db_session.commit()

    resp = await client.post(f"/api/v1/compliance/drift-events/{event.id}/acknowledge")
    assert resp.status_code == 200
    body = resp.json()
    assert body["acknowledged_by"] == current_user["id"]
    assert body["acknowledged_at"] is not None


@pytest.mark.asyncio
async def test_acknowledge_drift_event_404(client: AsyncClient):
    resp = await client.post(f"/api/v1/compliance/drift-events/{uuid.uuid4()}/acknowledge")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_policy_set_creates_job_without_crashing(client: AsyncClient):
    resp = await client.post(
        "/api/v1/compliance/policy-sets/import",
        json={
            "source": "complianceascode",
            "content_version": "test-v1",
            "datastream_url": "http://unreachable.invalid/ds.xml",
        },
    )
    # 202 proves the handler ran safe_user_uuid(current_user) and created
    # the Job row without raising — the background fetch itself will fail
    # (unreachable URL) but that's a separate, already-handled failure path.
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "QUEUED"
    assert body["job_id"]


@pytest.mark.asyncio
async def test_create_report_accepted(client: AsyncClient):
    resp = await client.post(
        "/api/v1/compliance/reports",
        json={"report_type": "FLEET_SUMMARY", "format": "JSON", "params": {}},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["report_type"] == "FLEET_SUMMARY"
    assert body["format"] == "JSON"
    assert body["status"] in ("PENDING", "GENERATING", "COMPLETED", "FAILED")


@pytest.mark.asyncio
async def test_list_reports(client: AsyncClient):
    resp = await client.get("/api/v1/compliance/reports")
    assert resp.status_code == 200
    assert "items" in resp.json()


@pytest.mark.asyncio
async def test_download_report_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/compliance/reports/{uuid.uuid4()}/download")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_report_formats_json_csv_always_true(client: AsyncClient):
    resp = await client.get("/api/v1/compliance/reports/formats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["JSON"] is True
    assert body["CSV"] is True


@pytest.mark.asyncio
async def test_report_formats_reflects_xlsx_pdf_setting(client: AsyncClient, db_session):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from lokilinux.models.audit import Setting

    await db_session.execute(
        pg_insert(Setting)
        .values(key="reports.xlsx_pdf_enabled", value="false", value_type="boolean")
        .on_conflict_do_update(index_elements=["key"], set_={"value": "false"})
    )
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/reports/formats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["XLSX"] is False
    assert body["PDF"] is False
