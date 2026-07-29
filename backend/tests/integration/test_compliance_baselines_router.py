"""Integration tests for /api/v1/compliance/baselines — CRUD + approval workflow."""

import uuid

import pytest
from httpx import AsyncClient

from lokilinux.models.baseline import Baseline, BaselineVersion


@pytest.mark.asyncio
async def test_create_baseline_seeds_draft_version_1(client: AsyncClient):
    resp = await client.post(
        "/api/v1/compliance/baselines",
        json={
            "name": "OL9 Database Servers",
            "scope_type": "ROLE",
            "scope_selector": {"role": "database"},
            "expected_state": {"sshd": {"PermitRootLogin": "no"}},
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["scope_type"] == "ROLE"

    versions_resp = await client.get(f"/api/v1/compliance/baselines/{body['id']}/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["status"] == "DRAFT"
    assert versions[0]["content_hash"]  # non-empty, deterministic hash was computed


@pytest.mark.asyncio
async def test_get_baseline_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/compliance/baselines/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_full_approval_workflow_to_publish(client: AsyncClient, db_session, fake_nats):
    author_id = uuid.uuid4()
    baseline = Baseline(name="global-default", scope_type="GLOBAL", scope_selector={}, created_by=author_id)
    db_session.add(baseline)
    await db_session.flush()
    version = BaselineVersion(
        baseline_id=baseline.id, version=1, status="DRAFT",
        expected_state={}, content_hash="deadbeef", created_by=author_id,
    )
    db_session.add(version)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/compliance/baselines/{baseline.id}/versions/{version.id}/submit"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PENDING_APPROVAL"

    resp = await client.post(
        f"/api/v1/compliance/baselines/{baseline.id}/versions/{version.id}/approve"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED"

    resp = await client.post(
        f"/api/v1/compliance/baselines/{baseline.id}/versions/{version.id}/publish"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PUBLISHED"
    assert body["published_at"] is not None
    assert any(subject == "lokilinux.compliance.baseline.published" for subject, _ in fake_nats.published)


@pytest.mark.asyncio
async def test_cannot_approve_from_draft(client: AsyncClient, db_session):
    author_id = uuid.uuid4()
    baseline = Baseline(name="b", scope_type="GLOBAL", scope_selector={}, created_by=author_id)
    db_session.add(baseline)
    await db_session.flush()
    version = BaselineVersion(
        baseline_id=baseline.id, version=1, status="DRAFT",
        expected_state={}, content_hash="x", created_by=author_id,
    )
    db_session.add(version)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/compliance/baselines/{baseline.id}/versions/{version.id}/approve"
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_rollback_requires_deprecated_status(client: AsyncClient, db_session):
    author_id = uuid.uuid4()
    baseline = Baseline(name="b", scope_type="GLOBAL", scope_selector={}, created_by=author_id)
    db_session.add(baseline)
    await db_session.flush()
    version = BaselineVersion(
        baseline_id=baseline.id, version=1, status="PUBLISHED",
        expected_state={}, content_hash="x", created_by=author_id,
    )
    db_session.add(version)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/compliance/baselines/{baseline.id}/versions/{version.id}/rollback"
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_effective_baseline_404_when_not_yet_computed(client: AsyncClient):
    resp = await client.get(f"/api/v1/compliance/agents/{uuid.uuid4()}/effective-baseline")
    assert resp.status_code == 404
