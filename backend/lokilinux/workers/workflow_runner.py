"""
LokiLinux — WorkflowRunnerWorker: advances every RUNNING workflow run.

Same shape as PolicySchedulerWorker/JobTimeoutWorker — its own asyncio loop,
no NATS event marks "a job finished, go check". Deliberately a poller, not
a hook wired into JobService.recompute_job_status (the way RemediationPlan's
_sync_remediation_plan is): the heartbeat interval (~60s per job dispatch)
already dwarfs a 5s poll delay, so the extra latency this adds is
negligible, and a poller can't drift out of sync the way a second directly-
maintained FK back onto `jobs` could (see models/workflow.py's WorkflowRun
docstring on why jobs.workflow_step_run_id doesn't exist).
"""

import asyncio

import structlog
from sqlalchemy import select

from lokilinux.models.workflow import WorkflowRun
from lokilinux.services.workflow_engine import advance_run

logger = structlog.get_logger()

_TICK_SECONDS = 5


class WorkflowRunnerWorker:
    def __init__(self, db_session_factory, cache, storage, nats=None) -> None:
        self.db_factory = db_session_factory
        self.cache = cache
        self.storage = storage
        self.nats = nats
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("WorkflowRunnerWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.error("workflow_runner.tick_failed", exc_info=True)
            await asyncio.sleep(_TICK_SECONDS)

    async def _tick(self) -> None:
        async with self.db_factory() as db:
            runs = (await db.execute(
                select(WorkflowRun).where(WorkflowRun.status == "RUNNING")
            )).scalars().all()
            for run in runs:
                await advance_run(db, self.cache, self.storage, run, self.nats)
