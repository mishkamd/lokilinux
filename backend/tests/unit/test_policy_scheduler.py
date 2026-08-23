"""
Unit tests for PolicySchedulerWorker — the atomic claim that stops two
replicas from firing the same SCHEDULE policy twice (no NATS-KV leader
election here, unlike the Go compliance service's own scheduler).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.job import Job
from lokilinux.models.policy import Policy
from lokilinux.models.workflow import Workflow
from lokilinux.workers.policy_scheduler import PolicySchedulerWorker


async def _make_agent(db_session) -> Agent:
    agent = Agent(agent_id=str(uuid.uuid4()), status=AgentStatus.ACTIVE, hostname="h")
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _make_due_policy(db_session, agent: Agent) -> Policy:
    policy = Policy(
        name="scheduled", rules={}, trigger_type="SCHEDULE", cron_expr="*/5 * * * *",
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # already due
        target_servers={"agent_ids": [str(agent.id)]},
        actions=[{"type": "PACKAGE_UPDATE", "params": {}}],
        created_by=uuid.uuid4(),
    )
    db_session.add(policy)
    await db_session.commit()
    return policy


@pytest.mark.asyncio
async def test_claim_and_run_creates_job_and_advances_next_run_at(db_session, fake_cache):
    agent = await _make_agent(db_session)
    policy = await _make_due_policy(db_session, agent)
    old_next_run = policy.next_run_at

    worker = PolicySchedulerWorker(db_session_factory=None, cache=fake_cache)
    await worker._claim_and_run(db_session, policy)

    jobs = (await db_session.execute(select(Job).where(Job.policy_id == policy.id))).scalars().all()
    assert len(jobs) == 1

    await db_session.refresh(policy)
    assert policy.next_run_at > old_next_run
    assert policy.last_run_at is not None


@pytest.mark.asyncio
async def test_claim_and_run_is_a_no_op_when_next_run_at_already_moved(db_session, fake_cache):
    """Simulates a second replica racing on the same tick: by the time it
    calls _claim_and_run, next_run_at no longer matches what it read, so its
    UPDATE ... WHERE next_run_at = <stale value> touches 0 rows and it must
    skip without creating a second job."""
    agent = await _make_agent(db_session)
    policy = await _make_due_policy(db_session, agent)

    worker = PolicySchedulerWorker(db_session_factory=None, cache=fake_cache)

    # Simulate "another replica already claimed it" by advancing next_run_at
    # out from under this call before it runs.
    stale_policy = Policy(**{c.name: getattr(policy, c.name) for c in Policy.__table__.columns})
    stale_policy.next_run_at = policy.next_run_at  # the value this "replica" observed
    policy.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db_session.commit()

    await worker._claim_and_run(db_session, stale_policy)

    jobs = (await db_session.execute(select(Job).where(Job.policy_id == policy.id))).scalars().all()
    assert len(jobs) == 0  # the race loser must not have created a job


@pytest.mark.asyncio
async def test_claim_and_run_invalid_cron_does_not_crash(db_session, fake_cache):
    agent = await _make_agent(db_session)
    policy = await _make_due_policy(db_session, agent)
    policy.cron_expr = "garbage"
    await db_session.commit()

    worker = PolicySchedulerWorker(db_session_factory=None, cache=fake_cache)
    await worker._claim_and_run(db_session, policy)  # must not raise

    jobs = (await db_session.execute(select(Job).where(Job.policy_id == policy.id))).scalars().all()
    assert len(jobs) == 0


@pytest.mark.asyncio
async def test_tick_skips_a_policy_migrated_to_a_workflow(db_session, fake_cache):
    """Migration plan §15 stage C: once a Workflow row points back at a
    policy via migrated_from_policy_id (services/policy_migration.py),
    WorkflowSchedulerWorker owns that cron — this worker's _tick must not
    also fire it, or a migrated policy would double-run on every tick."""
    from contextlib import asynccontextmanager

    agent = await _make_agent(db_session)
    policy = await _make_due_policy(db_session, agent)
    db_session.add(Workflow(
        name="migrated", slug=f"migrated-{policy.id}", migrated_from_policy_id=policy.id,
    ))
    await db_session.commit()

    @asynccontextmanager
    async def _factory():
        yield db_session

    worker = PolicySchedulerWorker(db_session_factory=_factory, cache=fake_cache)
    await worker._tick()

    jobs = (await db_session.execute(select(Job).where(Job.policy_id == policy.id))).scalars().all()
    assert len(jobs) == 0
    await db_session.refresh(policy)
    assert policy.last_run_at is None  # never claimed


@pytest.mark.asyncio
async def test_tick_still_fires_an_unmigrated_due_policy(db_session, fake_cache):
    """The skip filter must not swallow ordinary policies — only ones with
    an actual migrated_from_policy_id link."""
    from contextlib import asynccontextmanager

    agent = await _make_agent(db_session)
    policy = await _make_due_policy(db_session, agent)

    @asynccontextmanager
    async def _factory():
        yield db_session

    worker = PolicySchedulerWorker(db_session_factory=_factory, cache=fake_cache)
    await worker._tick()

    jobs = (await db_session.execute(select(Job).where(Job.policy_id == policy.id))).scalars().all()
    assert len(jobs) == 1
