"""Integration tests for /api/v1/ansible-roles — CRUD against
FakeObjectStorage (conftest.py), covering the Object Storage plan's
dual-read migration: new roles write their files map through
StorageService, the list endpoint returns file_count instead of the full
map (no S3 read per row), and get/update resolve files back from storage.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.ansible_role import AnsibleRole
from lokilinux.models.plugin import Plugin


@pytest.fixture(autouse=True)
async def _enable_ansible_plugin(db_session):
    plugin = (
        await db_session.execute(select(Plugin).where(Plugin.name == "ansible-automation"))
    ).scalar_one_or_none()
    if plugin is None:
        db_session.add(Plugin(
            name="ansible-automation", version="1.0.0",
            plugin_type="control-plane", is_enabled=True,
        ))
    else:
        plugin.is_enabled = True
    await db_session.commit()


@pytest.mark.asyncio
async def test_create_get_list_roundtrip(client: AsyncClient):
    files = {"tasks/main.yml": "---\n- name: noop\n", "defaults/main.yml": "---\n"}
    create_resp = await client.post(
        "/api/v1/ansible-roles", json={"name": "base", "files": files},
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["files"] == files
    role_id = body["id"]

    # List omits files, returns file_count instead.
    list_resp = await client.get("/api/v1/ansible-roles")
    assert list_resp.status_code == 200
    row = next(r for r in list_resp.json() if r["id"] == role_id)
    assert "files" not in row
    assert row["file_count"] == 2

    # Get resolves files back from storage.
    get_resp = await client.get(f"/api/v1/ansible-roles/{role_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["files"] == files


@pytest.mark.asyncio
async def test_update_files_bumps_version_and_file_count(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/ansible-roles", json={"name": "r", "files": {"tasks/main.yml": "---\n"}},
    )
    role_id = create_resp.json()["id"]

    new_files = {
        "tasks/main.yml": "---\n", "handlers/main.yml": "---\n", "defaults/main.yml": "---\n",
    }
    update_resp = await client.patch(f"/api/v1/ansible-roles/{role_id}", json={"files": new_files})
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["files"] == new_files
    assert body["version"] == 2

    list_resp = await client.get("/api/v1/ansible-roles")
    row = next(r for r in list_resp.json() if r["id"] == role_id)
    assert row["file_count"] == 3


@pytest.mark.asyncio
async def test_legacy_row_with_only_files_column_still_resolves(client: AsyncClient, db_session):
    """Dual-read fallback: a pre-migration row with `files` set directly
    and no content_object_id must keep working."""
    role = AnsibleRole(name="legacy-role", files={"tasks/main.yml": "---\nlegacy\n"}, file_count=1)
    db_session.add(role)
    await db_session.commit()
    await db_session.refresh(role)

    resp = await client.get(f"/api/v1/ansible-roles/{role.id}")
    assert resp.status_code == 200
    assert resp.json()["files"] == {"tasks/main.yml": "---\nlegacy\n"}


@pytest.mark.asyncio
async def test_delete_role(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/ansible-roles", json={"name": "gone", "files": {"tasks/main.yml": "---\n"}},
    )
    role_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/ansible-roles/{role_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/ansible-roles/{role_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_path_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/ansible-roles", json={"name": "bad", "files": {"../escape.yml": "---\n"}},
    )
    assert resp.status_code == 422
