"""Integration tests for /api/v1/policies — CRUD, version auto-increment, apply."""

import uuid

import pytest
from httpx import AsyncClient

from lokilinux.models.policy import Policy


@pytest.mark.asyncio
async def test_create_policy(client: AsyncClient):
    resp = await client.post("/api/v1/policies", json={
        "name": "weekly-patch",
        "policy_type": "UPDATE",
        "rules": {"schedule": "weekly"},
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["version"] == 1


@pytest.mark.asyncio
async def test_update_policy_increments_version(client: AsyncClient, db_session):
    policy = Policy(name="p1", rules={}, version=1, created_by=uuid.uuid4())
    db_session.add(policy)
    await db_session.commit()

    resp = await client.patch(f"/api/v1/policies/{policy.id}", json={"name": "p1-renamed"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 2
    assert body["name"] == "p1-renamed"


@pytest.mark.asyncio
async def test_get_policy_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/policies/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_policy(client: AsyncClient, db_session):
    policy = Policy(name="delete-me", rules={}, created_by=uuid.uuid4())
    db_session.add(policy)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/policies/{policy.id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/policies/{policy.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_apply_policy_publishes_to_nats(client: AsyncClient, db_session, fake_nats):
    policy = Policy(name="apply-me", rules={}, created_by=uuid.uuid4())
    db_session.add(policy)
    await db_session.commit()

    resp = await client.post(f"/api/v1/policies/{policy.id}/apply", json={"scope": "all"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "applying"
    assert any(subject == "lokilinux.policy.apply" for subject, _ in fake_nats.published)
