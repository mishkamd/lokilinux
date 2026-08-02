"""
Unit tests for PolicyService target resolution + policy-driven job creation.
"""

import uuid

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.job import Job
from lokilinux.models.policy import Policy, PolicyAudit
from lokilinux.services.policy_service import compute_next_run_at, resolve_targets, run_policy


async def _make_agent(db_session, **overrides) -> Agent:
    agent = Agent(
        agent_id=overrides.pop("agent_id", str(uuid.uuid4())),
        status=overrides.pop("status", AgentStatus.ACTIVE),
        hostname=overrides.pop("hostname", "h"),
        **overrides,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_resolve_targets_all(db_session):
    a1 = await _make_agent(db_session)
    a2 = await _make_agent(db_session)

    ids = await resolve_targets(db_session, {"all": True})

    assert set(ids) == {a1.id, a2.id}


@pytest.mark.asyncio
async def test_resolve_targets_agent_ids(db_session):
    a1 = await _make_agent(db_session)
    await _make_agent(db_session)  # not selected

    ids = await resolve_targets(db_session, {"agent_ids": [str(a1.id)]})

    assert ids == [a1.id]


@pytest.mark.asyncio
async def test_resolve_targets_filters_by_os_family(db_session):
    rocky = await _make_agent(db_session, os_family="linux", os_distro="rocky")
    await _make_agent(db_session, os_family="linux", os_distro="ubuntu")

    ids = await resolve_targets(db_session, {"filters": {"os_distro": "rocky"}})

    assert ids == [rocky.id]


@pytest.mark.asyncio
async def test_resolve_targets_empty_dict_matches_nothing(db_session):
    await _make_agent(db_session)

    assert await resolve_targets(db_session, {}) == []
    assert await resolve_targets(db_session, None) == []


@pytest.mark.asyncio
async def test_run_policy_creates_job_and_audit(db_session, fake_cache):
    agent = await _make_agent(db_session)
    policy = Policy(
        name="p", rules={}, target_servers={"agent_ids": [str(agent.id)]},
        actions=[{"type": "PACKAGE_UPDATE", "params": {"package_names": ["curl"]}}],
        created_by=uuid.uuid4(),
    )
    db_session.add(policy)
    await db_session.commit()

    job_ids, matched = await run_policy(db_session, policy, fake_cache, triggered_by="manual")

    assert matched == 1
    assert len(job_ids) == 1

    job = await db_session.get(Job, job_ids[0])
    assert job.job_type == "PACKAGE_UPDATE"
    assert job.policy_id == policy.id
    assert job.parameters == {"package_names": ["curl"]}

    audit_rows = (
        await db_session.execute(select(PolicyAudit).where(PolicyAudit.policy_id == policy.id))
    ).scalars().all()
    assert len(audit_rows) == 1
    assert audit_rows[0].change_type == "TRIGGERED"
    assert audit_rows[0].new_value["matched_agents"] == 1


@pytest.mark.asyncio
async def test_run_policy_skips_quietly_on_active_duplicate(db_session, fake_cache):
    """A policy re-firing (e.g. a tight cron over a still-running job) must
    not raise — JobService's own dedup already protects the DB, run_policy
    just needs to not crash on that ValueError."""
    agent = await _make_agent(db_session)
    policy = Policy(
        name="p", rules={}, target_servers={"agent_ids": [str(agent.id)]},
        actions=[{"type": "PACKAGE_UPDATE", "params": {}}], created_by=uuid.uuid4(),
    )
    db_session.add(policy)
    await db_session.commit()

    first_job_ids, _ = await run_policy(db_session, policy, fake_cache, triggered_by="manual")
    assert len(first_job_ids) == 1

    second_job_ids, matched = await run_policy(db_session, policy, fake_cache, triggered_by="manual")
    assert second_job_ids == []
    assert matched == 1  # targets still resolved fine, just no new job


@pytest.mark.asyncio
async def test_run_policy_no_actions_creates_no_job(db_session, fake_cache):
    agent = await _make_agent(db_session)
    policy = Policy(
        name="p", rules={}, target_servers={"agent_ids": [str(agent.id)]},
        actions=[], created_by=uuid.uuid4(),
    )
    db_session.add(policy)
    await db_session.commit()

    job_ids, matched = await run_policy(db_session, policy, fake_cache, triggered_by="manual")

    assert job_ids == []
    assert matched == 1


def test_compute_next_run_at_is_strictly_after_base():
    from datetime import datetime, timezone
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    next_run = compute_next_run_at("0 2 * * *", base)

    assert next_run > base
    assert next_run.hour == 2


def test_compute_next_run_at_rejects_garbage():
    with pytest.raises(Exception):
        compute_next_run_at("not a cron expression")
