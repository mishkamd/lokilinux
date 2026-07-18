"""Integration tests for /api/v1/jobs — create, list, cancel."""

import uuid

import pytest
from httpx import AsyncClient

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.job import Job, JobStatus


async def _make_agent(db_session, **overrides) -> Agent:
    agent = Agent(
        agent_id=overrides.pop("agent_id", str(uuid.uuid4())),
        status=overrides.pop("status", AgentStatus.ACTIVE),
        hostname=overrides.pop("hostname", "web-01"),
        **overrides,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_create_job(client: AsyncClient, db_session):
    agent = await _make_agent(db_session)
    await db_session.commit()

    resp = await client.post("/api/v1/jobs", json={
        "name": "patch servers",
        "job_type": "PACKAGE_UPDATE",
        "target_servers": {"agent_ids": [str(agent.id)]},
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "QUEUED"
    assert body["dedup_key"]


@pytest.mark.asyncio
async def test_create_job_dedup_key_varies_by_type(client: AsyncClient, db_session):
    agent = await _make_agent(db_session)
    await db_session.commit()

    payload = {
        "name": "patch servers",
        "job_type": "PACKAGE_UPDATE",
        "target_servers": {"agent_ids": [str(agent.id)]},
    }
    r1 = await client.post("/api/v1/jobs", json=payload)
    r2 = await client.post("/api/v1/jobs", json={**payload, "job_type": "SECURITY_PATCH"})
    assert r1.json()["dedup_key"] != r2.json()["dedup_key"]


@pytest.mark.asyncio
async def test_create_job_fans_out_job_results(client: AsyncClient, db_session):
    a1 = await _make_agent(db_session)
    a2 = await _make_agent(db_session, hostname="web-02")
    await db_session.commit()

    resp = await client.post("/api/v1/jobs", json={
        "name": "multi-agent job",
        "job_type": "PACKAGE_UPDATE",
        "target_servers": {"agent_ids": [str(a1.id), str(a2.id)]},
    })
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    results = await client.get(f"/api/v1/jobs/{job_id}/results")
    assert results.status_code == 200
    body = results.json()
    assert len(body) == 2
    assert all(r["status"] == "PENDING" for r in body)
    assert {r["hostname"] for r in body} == {"web-01", "web-02"}


@pytest.mark.asyncio
async def test_list_jobs_filters_by_agent_id(client: AsyncClient, db_session):
    await _make_agent(db_session, agent_id="agent-a")
    await _make_agent(db_session, agent_id="agent-b")
    creator = uuid.uuid4()
    db_session.add(Job(name="a-job", job_type="PACKAGE_UPDATE", target_servers={"agent_ids": ["agent-a"]}, status=JobStatus.QUEUED, created_by=creator))
    db_session.add(Job(name="b-job", job_type="PACKAGE_UPDATE", target_servers={"agent_ids": ["agent-b"]}, status=JobStatus.QUEUED, created_by=creator))
    await db_session.commit()

    resp = await client.get("/api/v1/jobs", params={"agent_id": "agent-a"})
    assert resp.status_code == 200
    names = [j["name"] for j in resp.json()["items"]]
    assert names == ["a-job"]


@pytest.mark.asyncio
async def test_cancel_queued_job(client: AsyncClient, db_session):
    job = Job(name="cancel-me", job_type="PACKAGE_UPDATE", target_servers={}, status=JobStatus.QUEUED)
    db_session.add(job)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/jobs/{job.id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_cancel_running_job_returns_409(client: AsyncClient, db_session):
    job = Job(name="running", job_type="PACKAGE_UPDATE", target_servers={}, status=JobStatus.RUNNING)
    db_session.add(job)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/jobs/{job.id}")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_job_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404
