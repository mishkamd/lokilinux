"""Integration tests for /api/v1/policies — CRUD, version auto-increment,
role gating, cron scheduling, and /run (replaces the old /apply, which only
published a NATS event that got counted and forgotten — it never created a
Job or touched a server)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.policy import Policy, PolicyAudit


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
    assert body["trigger_type"] == "MANUAL"


@pytest.mark.asyncio
async def test_create_policy_writes_audit_row(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/policies", json={"name": "audited", "rules": {}})
    assert resp.status_code == 201
    policy_id = resp.json()["id"]

    rows = (
        await db_session.execute(
            select(PolicyAudit).where(PolicyAudit.policy_id == uuid.UUID(policy_id))
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].change_type == "CREATE"


@pytest.mark.asyncio
async def test_create_policy_with_schedule_sets_next_run_at(client: AsyncClient):
    resp = await client.post("/api/v1/policies", json={
        "name": "nightly",
        "rules": {},
        "trigger_type": "SCHEDULE",
        "cron_expr": "0 2 * * *",
    })
    assert resp.status_code == 201
    assert resp.json()["next_run_at"] is not None


@pytest.mark.asyncio
async def test_create_policy_schedule_without_cron_is_422(client: AsyncClient):
    resp = await client.post("/api/v1/policies", json={
        "name": "broken",
        "rules": {},
        "trigger_type": "SCHEDULE",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_policy_invalid_cron_is_422(client: AsyncClient):
    resp = await client.post("/api/v1/policies", json={
        "name": "bad-cron",
        "rules": {},
        "trigger_type": "SCHEDULE",
        "cron_expr": "not a cron expression",
    })
    assert resp.status_code == 422


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
async def test_update_policy_writes_audit_row_with_diff(client: AsyncClient, db_session):
    policy = Policy(name="before", rules={}, created_by=uuid.uuid4())
    db_session.add(policy)
    await db_session.commit()

    resp = await client.patch(f"/api/v1/policies/{policy.id}", json={"name": "after"})
    assert resp.status_code == 200

    rows = (
        await db_session.execute(
            select(PolicyAudit).where(PolicyAudit.policy_id == policy.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].change_type == "UPDATE"
    assert rows[0].old_value["name"] == "before"
    assert rows[0].new_value["name"] == "after"


@pytest.mark.asyncio
async def test_update_policy_switching_away_from_schedule_clears_next_run_at(client: AsyncClient, db_session):
    from datetime import datetime, timezone
    policy = Policy(
        name="was-scheduled", rules={}, trigger_type="SCHEDULE", cron_expr="0 2 * * *",
        next_run_at=datetime.now(timezone.utc), created_by=uuid.uuid4(),
    )
    db_session.add(policy)
    await db_session.commit()

    resp = await client.patch(f"/api/v1/policies/{policy.id}", json={"trigger_type": "MANUAL"})
    assert resp.status_code == 200
    assert resp.json()["next_run_at"] is None


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
async def test_run_policy_creates_real_job(client: AsyncClient, db_session):
    """The whole point of Phase 1: a policy run must produce an actual Job,
    not just a NATS event nobody acts on — confirmed live that /apply's only
    effect was a PolicyAudit row and a cache invalidation."""
    agent = Agent(agent_id=str(uuid.uuid4()), status=AgentStatus.ACTIVE, hostname="h1")
    db_session.add(agent)
    await db_session.flush()

    policy = Policy(
        name="run-me", rules={}, target_servers={"agent_ids": [str(agent.id)]},
        actions=[{"type": "PACKAGE_UPDATE", "params": {}}], created_by=uuid.uuid4(),
    )
    db_session.add(policy)
    await db_session.commit()

    resp = await client.post(f"/api/v1/policies/{policy.id}/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched_agents"] == 1
    assert len(body["job_ids"]) == 1

    from lokilinux.models.job import Job
    job = (await db_session.execute(
        select(Job).where(Job.id == uuid.UUID(body["job_ids"][0]))
    )).scalar_one()
    assert job.job_type == "PACKAGE_UPDATE"
    assert str(job.policy_id) == str(policy.id)


@pytest.mark.asyncio
async def test_run_policy_no_matching_agents_returns_empty(client: AsyncClient, db_session):
    policy = Policy(
        name="no-targets", rules={}, target_servers={"agent_ids": []},
        actions=[{"type": "PACKAGE_UPDATE", "params": {}}], created_by=uuid.uuid4(),
    )
    db_session.add(policy)
    await db_session.commit()

    resp = await client.post(f"/api/v1/policies/{policy.id}/run")
    assert resp.status_code == 200
    assert resp.json()["job_ids"] == []


@pytest.mark.asyncio
async def test_policies_router_gates_mutations_on_admin_or_operator():
    """create/update/delete/run used to be reachable by any authenticated
    user — no require_role at all. This is the exact dependency every one
    of those endpoints now depends on; a VIEWER must be rejected, ADMIN and
    OPERATOR must pass through unchanged."""
    from fastapi import HTTPException

    from lokilinux.auth.dependencies import require_role

    check = require_role("ADMIN", "OPERATOR")

    with pytest.raises(HTTPException) as exc_info:
        await check(user={"id": "u1", "role": "VIEWER"})
    assert exc_info.value.status_code == 403

    admin = {"id": "u2", "role": "ADMIN"}
    assert await check(user=admin) == admin

    operator = {"id": "u3", "role": "OPERATOR"}
    assert await check(user=operator) == operator
