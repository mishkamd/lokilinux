"""Integration tests for POST /api/v1/admin/kms/keys/{key_id}/rotate."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.audit import AuditLog


@pytest.mark.asyncio
async def test_rotate_without_versioned_layout_returns_409(client: AsyncClient, monkeypatch):
    monkeypatch.delenv("LOKILINUX_KEYS_DIR", raising=False)
    resp = await client.post("/api/v1/admin/kms/keys/job-signing/rotate")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_rotate_creates_versions_and_audits(client: AsyncClient, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(tmp_path / "keys"))

    resp = await client.post("/api/v1/admin/kms/keys/job-signing/rotate")
    assert resp.status_code == 200
    assert resp.json() == {"key_id": "job-signing", "previous_version": None, "active_version": 1}

    resp = await client.post("/api/v1/admin/kms/keys/job-signing/rotate")
    assert resp.status_code == 200
    assert resp.json() == {"key_id": "job-signing", "previous_version": 1, "active_version": 2}

    rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "kms.key.rotated"))
    ).scalars().all()
    assert len(rows) == 2
    assert rows[-1].resource_id == "job-signing"
    assert rows[-1].changes == {"from_version": 1, "to_version": 2}
