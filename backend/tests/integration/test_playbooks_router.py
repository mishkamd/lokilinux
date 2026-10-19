"""Integration tests for /api/v1/playbooks — CRUD + execute against
FakeObjectStorage (conftest.py), covering the Object Storage plan's
dual-read migration: new playbooks write content through StorageService,
the list endpoint omits content (no S3 read per row), and get/update
resolve it back from storage.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.playbook import Playbook
from lokilinux.models.plugin import Plugin


@pytest.fixture(autouse=True)
async def _enable_ansible_plugin(db_session):
    # migration 009_add_playbooks seeds this row already disabled — flip it
    # on for the duration of the test instead of inserting a duplicate.
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
    create_resp = await client.post(
        "/api/v1/playbooks",
        json={"name": "web-restart", "content": "- hosts: all\n  tasks: []\n"},
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["content"] == "- hosts: all\n  tasks: []\n"
    playbook_id = body["id"]

    # List omits content — no object-storage read per row.
    list_resp = await client.get("/api/v1/playbooks")
    assert list_resp.status_code == 200
    row = next(p for p in list_resp.json() if p["id"] == playbook_id)
    assert "content" not in row

    # Get resolves content back from storage.
    get_resp = await client.get(f"/api/v1/playbooks/{playbook_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["content"] == "- hosts: all\n  tasks: []\n"


@pytest.mark.asyncio
async def test_update_content_bumps_version_and_resolves(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/playbooks", json={"name": "p", "content": "- hosts: all\n  tasks: []\n"},
    )
    playbook_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/playbooks/{playbook_id}", json={"content": "- hosts: web\n  tasks: []\n"},
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["content"] == "- hosts: web\n  tasks: []\n"
    assert body["version"] == 2


@pytest.mark.asyncio
async def test_update_without_content_change_keeps_version(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/playbooks", json={"name": "p", "content": "- hosts: all\n  tasks: []\n"},
    )
    playbook_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/playbooks/{playbook_id}", json={"description": "updated"}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 1


@pytest.mark.asyncio
async def test_legacy_row_with_only_content_column_still_resolves(client: AsyncClient, db_session):
    """Dual-read fallback: a pre-migration row with `content` set directly
    and no content_object_id must keep working."""
    playbook = Playbook(name="legacy", content="- hosts: legacy\n  tasks: []\n")
    db_session.add(playbook)
    await db_session.commit()
    await db_session.refresh(playbook)

    resp = await client.get(f"/api/v1/playbooks/{playbook.id}")
    assert resp.status_code == 200
    assert resp.json()["content"] == "- hosts: legacy\n  tasks: []\n"


@pytest.mark.asyncio
async def test_delete_playbook(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/playbooks", json={"name": "gone", "content": "- hosts: all\n  tasks: []\n"},
    )
    playbook_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/playbooks/{playbook_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/playbooks/{playbook_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_execute_snapshots_content_into_job(client: AsyncClient, db_session):
    from sqlalchemy import select

    from lokilinux.models.agent import Agent, AgentStatus
    from lokilinux.models.job import Job

    agent = Agent(agent_id="test-agent-1", hostname="h1", status=AgentStatus.ACTIVE)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    create_resp = await client.post(
        "/api/v1/playbooks", json={"name": "run-me", "content": "- hosts: all\n  tasks: []\n"},
    )
    playbook_id = create_resp.json()["id"]

    exec_resp = await client.post(
        f"/api/v1/playbooks/{playbook_id}/execute", json={"agent_ids": [str(agent.id)]},
    )
    assert exec_resp.status_code == 201
    job_id = exec_resp.json()["id"]

    job = (await db_session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    assert job.parameters["playbook_content"] == "- hosts: all\n  tasks: []\n"
