"""/policy-sets/import refuses a datastream URL aimed at the cloud metadata address
(ROADMAP P1r-2). The SSRF guard is NOT disabled here. The other import tests
monkeypatch assert_safe_url away, so they can't show that the refusal happens.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from lokilinux.models.job import Job


@pytest.mark.asyncio
async def test_import_refuses_metadata_datastream_url(client: AsyncClient, db_session):
    resp = await client.post(
        "/api/v1/compliance/policy-sets/import",
        json={
            "source": "complianceascode",
            "content_version": "test-v1",
            "datastream_url": "http://169.254.169.254/latest/meta-data/",
        },
    )
    assert resp.status_code == 422
    # Match the guard's message, not just the status, so a schema 422 can't pass for it.
    assert "datastream_url refused" in resp.json()["detail"]
    assert "blocked address" in resp.json()["detail"]

    # Refused before the Job row is created, so no import is queued.
    queued = await db_session.scalar(
        select(func.count()).select_from(Job).where(
            Job.job_type == "COMPLIANCE_IMPORT_CONTENT"
        )
    )
    assert queued == 0
