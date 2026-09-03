"""Integration tests for /api/v1/storage — upload/list/download/verify/delete.

Runs against FakeObjectStorage (conftest.py) — no real S3/RustFS involved,
same pattern as FakeCache/FakeNats/FakeCH for the other backing services.
"""

import hashlib

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_upload_list_download_roundtrip(client: AsyncClient):
    content = b"hello world" * 100
    resp = await client.post(
        "/api/v1/storage/objects",
        params={"category": "upload"},
        files={"file": ("notes.txt", content, "text/plain")},
    )
    assert resp.status_code == 201
    obj = resp.json()
    assert obj["category"] == "upload"
    assert obj["sha256"] == hashlib.sha256(content).hexdigest()
    assert obj["size_bytes"] == len(content)

    list_resp = await client.get("/api/v1/storage/objects", params={"category": "upload"})
    assert list_resp.status_code == 200
    assert any(o["id"] == obj["id"] for o in list_resp.json()["items"])

    meta_resp = await client.get(f"/api/v1/storage/objects/{obj['id']}")
    assert meta_resp.status_code == 200
    assert meta_resp.json()["filename"] == "notes.txt"

    download_resp = await client.get(f"/api/v1/storage/objects/{obj['id']}/download")
    assert download_resp.status_code == 200
    assert download_resp.content == content


@pytest.mark.asyncio
async def test_verify_matches_recorded_sha256(client: AsyncClient):
    content = b"verify me"
    resp = await client.post(
        "/api/v1/storage/objects",
        params={"category": "upload"},
        files={"file": ("f.txt", content, "text/plain")},
    )
    object_id = resp.json()["id"]

    verify_resp = await client.post(f"/api/v1/storage/objects/{object_id}/verify")
    assert verify_resp.status_code == 200
    body = verify_resp.json()
    assert body["sha256_match"] is True
    assert body["sha256_recorded"] == hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
async def test_delete_object_then_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/storage/objects",
        params={"category": "upload"},
        files={"file": ("gone.txt", b"bye", "text/plain")},
    )
    object_id = resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/storage/objects/{object_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/storage/objects/{object_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_unknown_category_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/storage/objects",
        params={"category": "not-a-real-category"},
        files={"file": ("f.txt", b"x", "text/plain")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_presign_disabled_without_public_endpoint(client: AsyncClient):
    resp = await client.post(
        "/api/v1/storage/objects",
        params={"category": "upload"},
        files={"file": ("f.txt", b"x", "text/plain")},
    )
    object_id = resp.json()["id"]

    presign_resp = await client.get(
        f"/api/v1/storage/objects/{object_id}/download", params={"presign": "true"}
    )
    assert presign_resp.status_code == 409


@pytest.mark.asyncio
async def test_download_missing_object_404(client: AsyncClient):
    resp = await client.get(
        "/api/v1/storage/objects/00000000-0000-0000-0000-000000000000/download"
    )
    assert resp.status_code == 404
