"""Saved views (MIS-191) — a view belongs to the user who saved it.

The security-relevant property: one user cannot read or delete another
user's view. Everything else (create/list/replace by scope+name) is plain
round-trip coverage.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.saved_view import SavedView


@pytest.mark.asyncio
async def test_saved_view_round_trip(client: AsyncClient, db_session):
    resp = await client.post(
        "/api/v1/account/views",
        json={"scope": "servers", "name": "Prod", "path": "/servers", "query": {"status": "ACTIVE"}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Prod"
    assert body["query"] == {"status": "ACTIVE"}

    listed = await client.get("/api/v1/account/views?scope=servers")
    assert listed.status_code == 200
    names = [v["name"] for v in listed.json()]
    assert "Prod" in names

    # saving the same name in the same scope replaces it, it doesn't duplicate
    resp = await client.post(
        "/api/v1/account/views",
        json={"scope": "servers", "name": "Prod", "path": "/servers", "query": {"status": "INACTIVE"}},
    )
    assert resp.status_code == 201
    listed = await client.get("/api/v1/account/views?scope=servers")
    prod = [v for v in listed.json() if v["name"] == "Prod"]
    assert len(prod) == 1
    assert prod[0]["query"] == {"status": "INACTIVE"}


@pytest.mark.asyncio
async def test_saved_view_is_scoped_to_its_owner(client: AsyncClient, db_session):
    other = SavedView(
        user_id=f"other-{uuid.uuid4().hex[:8]}",
        scope="servers",
        name="Theirs",
        path="/servers",
        query={},
    )
    db_session.add(other)
    await db_session.commit()

    listed = await client.get("/api/v1/account/views")
    assert "Theirs" not in [v["name"] for v in listed.json()]

    resp = await client.delete(f"/api/v1/account/views/{other.id}")
    assert resp.status_code == 404

    still_there = (
        await db_session.execute(select(SavedView).where(SavedView.id == other.id))
    ).scalar_one()
    assert still_there is not None


@pytest.mark.asyncio
async def test_saved_view_delete(client: AsyncClient, db_session):
    resp = await client.post(
        "/api/v1/account/views",
        json={"scope": "jobs", "name": "Failed", "path": "/jobs", "query": {"status": "FAILED"}},
    )
    view_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/account/views/{view_id}")
    assert resp.status_code == 204

    listed = await client.get("/api/v1/account/views?scope=jobs")
    assert listed.json() == []
