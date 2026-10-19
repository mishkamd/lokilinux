"""
LokiLinux — WorkflowSchedulerWorker: fires SCHEDULE-trigger workflows whose
next_run_at has arrived.

Exact same shape and claim strategy as PolicySchedulerWorker — an atomic
`UPDATE ... WHERE next_run_at = <value we last saw>` is what stops two API
replicas from firing the same workflow twice, without needing NATS-KV
leader election like the Go compliance service's scheduler.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update

from lokilinux.models.workflow import Workflow
from lokilinux.services.policy_service import compute_next_run_at
from lokilinux.services.workflow_engine import start_run

logger = structlog.get_logger()

_TICK_SECONDS = 30


class WorkflowSchedulerWorker:
    def __init__(self, db_session_factory, cache, storage) -> None:
        self.db_factory = db_session_factory
        self.cache = cache
        self.storage = storage
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("WorkflowSchedulerWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.error("workflow_scheduler.tick_failed", exc_info=True)
            await asyncio.sleep(_TICK_SECONDS)

    async def _tick(self) -> None:
        async with self.db_factory() as db:
            now = datetime.now(timezone.utc)
            due = (await db.execute(
                select(Workflow).where(
                    Workflow.is_enabled.is_(True),
                    Workflow.trigger_type == "SCHEDULE",
                    Workflow.next_run_at.isnot(None),
                    Workflow.next_run_at <= now,
                    Workflow.current_version_id.isnot(None),
                )
            )).scalars().all()

            for workflow in due:
                await self._claim_and_run(db, workflow)

    async def _claim_and_run(self, db, workflow: Workflow) -> None:
        seen_next_run_at = workflow.next_run_at
        now = datetime.now(timezone.utc)
        try:
            new_next_run_at = compute_next_run_at(workflow.cron_expr, now)
        except Exception:
            logger.error("workflow_scheduler.invalid_cron", workflow_id=str(workflow.id), cron_expr=workflow.cron_expr, exc_info=True)
            return

        result = await db.execute(
            update(Workflow)
            .where(Workflow.id == workflow.id, Workflow.next_run_at == seen_next_run_at)
            .values(next_run_at=new_next_run_at, last_run_at=now)
        )
        await db.commit()
        if result.rowcount != 1:
            return  # another replica already claimed this tick

        try:
            run = await start_run(
                db, self.cache, self.storage, workflow.id,
                trigger_type="SCHEDULE", triggered_by=None,
            )
            logger.info("workflow.scheduled_run", workflow_id=str(workflow.id), run_id=str(run.id))
        except Exception:
            # A workflow whose targets no longer resolve (or whose current
            # version was unpublished between claim and dispatch) must not
            # crash the scheduler loop for every other due workflow.
            logger.error("workflow_scheduler.run_failed", workflow_id=str(workflow.id), exc_info=True)
