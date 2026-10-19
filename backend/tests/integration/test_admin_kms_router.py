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



@pytest.mark.asyncio
async def test_get_versions_without_versioned_layout_returns_409(client: AsyncClient, monkeypatch):
    monkeypatch.delenv("LOKILINUX_KEYS_DIR", raising=False)
    resp = await client.get("/api/v1/admin/kms/keys/job-signing")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_stage_then_activate_then_retire(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(tmp_path / "keys"))

    resp = await client.get("/api/v1/admin/kms/keys/job-signing")
    assert resp.status_code == 200
    assert resp.json() == {"key_id": "job-signing", "versions": {}}

    resp = await client.post("/api/v1/admin/kms/keys/job-signing/versions")
    assert resp.status_code == 200
    assert resp.json() == {"key_id": "job-signing", "version": 1, "state": "VERIFY_ONLY"}

    resp = await client.get("/api/v1/admin/kms/keys/job-signing")
    assert resp.json()["versions"] == {"1": "VERIFY_ONLY"}

    resp = await client.patch(
        "/api/v1/admin/kms/keys/job-signing/versions/1", json={"state": "ACTIVE"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"key_id": "job-signing", "version": 1, "state": "ACTIVE"}

    resp = await client.post("/api/v1/admin/kms/keys/job-signing/versions")
    assert resp.json() == {"key_id": "job-signing", "version": 2, "state": "VERIFY_ONLY"}

    resp = await client.patch(
        "/api/v1/admin/kms/keys/job-signing/versions/2", json={"state": "ACTIVE"}
    )
    assert resp.status_code == 200

    # v1 (now VERIFY_ONLY, not ACTIVE) can be retired.
    resp = await client.patch(
        "/api/v1/admin/kms/keys/job-signing/versions/1", json={"state": "RETIRED"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"key_id": "job-signing", "version": 1, "state": "RETIRED"}

    resp = await client.get("/api/v1/admin/kms/keys/job-signing")
    assert resp.json()["versions"] == {"1": "RETIRED", "2": "ACTIVE"}

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.resource_id == "job-signing").order_by(AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    actions = [r.action for r in rows]
    assert actions == [
        "kms.key.staged",
        "kms.key.activated",
        "kms.key.staged",
        "kms.key.activated",
        "kms.key.retired",
    ]


@pytest.mark.asyncio
async def test_retire_active_version_rejected(client: AsyncClient, tmp_path, monkeypatch):
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(tmp_path / "keys"))
    await client.post("/api/v1/admin/kms/keys/job-signing/versions")
    await client.patch("/api/v1/admin/kms/keys/job-signing/versions/1", json={"state": "ACTIVE"})

    resp = await client.patch(
        "/api/v1/admin/kms/keys/job-signing/versions/1", json={"state": "RETIRED"}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_activate_unknown_version_returns_500(client: AsyncClient, tmp_path, monkeypatch):
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(tmp_path / "keys"))
    resp = await client.patch(
        "/api/v1/admin/kms/keys/job-signing/versions/9", json={"state": "ACTIVE"}
    )
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_set_version_state_rejects_invalid_state(client: AsyncClient, tmp_path, monkeypatch):
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(tmp_path / "keys"))
    resp = await client.patch(
        "/api/v1/admin/kms/keys/job-signing/versions/1", json={"state": "BOGUS"}
    )
    assert resp.status_code == 422
