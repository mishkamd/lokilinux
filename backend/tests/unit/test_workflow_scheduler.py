"""
Unit tests for WorkflowSchedulerWorker — same atomic claim contract as
PolicySchedulerWorker (tests/unit/test_policy_scheduler.py), applied to a
published, SCHEDULE-trigger Workflow instead of a Policy.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.workflow import Workflow, WorkflowRun
from lokilinux.services.workflow_service import WorkflowService
from lokilinux.workers.workflow_scheduler import WorkflowSchedulerWorker

LINEAR_YAML = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: scheduler-test-wf
spec:
  targets: { all: true }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
  edges: []
"""


async def _make_agent(db_session) -> Agent:
    agent = Agent(agent_id=str(uuid.uuid4()), status=AgentStatus.ACTIVE, hostname="h")
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _make_due_scheduled_workflow(db_session, fake_storage, slug: str) -> Workflow:
    svc = WorkflowService(db_session, fake_storage)
    workflow = await svc.create_workflow(
        name="Scheduled", yaml_source=LINEAR_YAML.replace("scheduler-test-wf", slug), created_by=None,
    )
    from lokilinux.models.workflow import WorkflowVersion
    version = (await db_session.execute(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
    )).scalar_one()
    await svc.publish_version(workflow.id, version.id, actor=None)

    workflow.trigger_type = "SCHEDULE"
    workflow.cron_expr = "*/5 * * * *"
    workflow.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)  # already due
    await db_session.commit()
    await db_session.refresh(workflow)
    return workflow


@pytest.mark.asyncio
async def test_claim_and_run_starts_a_run_and_advances_next_run_at(
    db_session, fake_cache, fake_storage
):
    await _make_agent(db_session)
    workflow = await _make_due_scheduled_workflow(db_session, fake_storage, "scheduler-claim-test")
    old_next_run = workflow.next_run_at

    worker = WorkflowSchedulerWorker(
        db_session_factory=None, cache=fake_cache, storage=fake_storage
    )
    await worker._claim_and_run(db_session, workflow)

    runs = (await db_session.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id))).scalars().all()
    assert len(runs) == 1
    assert runs[0].trigger_type == "SCHEDULE"

    await db_session.refresh(workflow)
    assert workflow.next_run_at > old_next_run
    assert workflow.last_run_at is not None


@pytest.mark.asyncio
async def test_claim_and_run_is_a_no_op_when_next_run_at_already_moved(
    db_session, fake_cache, fake_storage
):
    """Same race-loser scenario as test_policy_scheduler.py's equivalent
    test: a second replica's UPDATE ... WHERE next_run_at = <stale value>
    touches 0 rows once another replica already claimed the tick."""
    await _make_agent(db_session)
    workflow = await _make_due_scheduled_workflow(db_session, fake_storage, "scheduler-race-test")

    worker = WorkflowSchedulerWorker(
        db_session_factory=None, cache=fake_cache, storage=fake_storage
    )

    stale_workflow = Workflow(**{c.name: getattr(workflow, c.name) for c in Workflow.__table__.columns})
    stale_workflow.next_run_at = workflow.next_run_at  # the value this "replica" observed
    workflow.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db_session.commit()

    await worker._claim_and_run(db_session, stale_workflow)

    runs = (await db_session.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id))).scalars().all()
    assert len(runs) == 0  # the race loser must not have started a run


@pytest.mark.asyncio
async def test_claim_and_run_invalid_cron_does_not_crash(db_session, fake_cache, fake_storage):
    await _make_agent(db_session)
    workflow = await _make_due_scheduled_workflow(
        db_session, fake_storage, "scheduler-badcron-test"
    )
    workflow.cron_expr = "garbage"
    await db_session.commit()

    worker = WorkflowSchedulerWorker(
        db_session_factory=None, cache=fake_cache, storage=fake_storage
    )
    await worker._claim_and_run(db_session, workflow)  # must not raise

    runs = (await db_session.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id))).scalars().all()
    assert len(runs) == 0


@pytest.mark.asyncio
async def test_claim_and_run_with_no_matching_agents_does_not_crash(
    db_session, fake_cache, fake_storage
):
    """start_run raises HTTPException(422) when no agents match — the
    scheduler's broad except must swallow that too, not just cron errors,
    or one misconfigured workflow would wedge every other due workflow on
    the same tick."""
    # no agent created
    workflow = await _make_due_scheduled_workflow(
        db_session, fake_storage, "scheduler-noagents-test"
    )

    worker = WorkflowSchedulerWorker(
        db_session_factory=None, cache=fake_cache, storage=fake_storage
    )
    await worker._claim_and_run(db_session, workflow)  # must not raise

    runs = (await db_session.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id))).scalars().all()
    assert len(runs) == 0
