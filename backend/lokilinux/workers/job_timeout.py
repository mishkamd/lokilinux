"""
LokiLinux — JobTimeoutWorker: periodic stale-job sweep.

Not NATS-driven, same reasoning as HeartbeatMonitorWorker — there's no event
for "an agent silently never reported back". A Job stuck in a non-terminal
state (QUEUED/SCHEDULED/PENDING/RUNNING) past fleet.job_stale_timeout_minutes
means the target agent isn't executing it — usually a dead/stale agent
binary — and would otherwise block every future identical job forever via
JobService.create_job's dedup_key check. Marks the Job and its still-open
JobResult rows TIMEOUT so the dedup key frees up and the real state is
visible in the UI instead of an eternal QUEUED.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from lokilinux.models.job import Job, JobResult, JobStatus
from lokilinux.settings_schema import get_setting_value

logger = structlog.get_logger()

_SWEEP_INTERVAL_SECONDS = 60
_NON_TERMINAL = (JobStatus.QUEUED, JobStatus.SCHEDULED, JobStatus.PENDING, JobStatus.RUNNING)


class JobTimeoutWorker:
    def __init__(self, session_factory, cache) -> None:
        self.db_factory = session_factory
        self.cache = cache
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("JobTimeoutWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._sweep()
            except Exception:
                logger.error("job_timeout.sweep_failed", exc_info=True)
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)

    async def _sweep(self) -> None:
        async with self.db_factory() as db:
            timeout_minutes = await get_setting_value(db, "fleet.job_stale_timeout_minutes")
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

            stale = (
                await db.execute(
                    select(Job).where(Job.status.in_(_NON_TERMINAL), Job.created_at < cutoff)
                )
            ).scalars().all()

            if not stale:
                return

            for job in stale:
                job.status = JobStatus.TIMEOUT
                await db.execute(
                    JobResult.__table__.update()
                    .where(JobResult.job_id == job.id, JobResult.status.in_(("PENDING", "RUNNING")))
                    .values(status="TIMEOUT", completed_at=datetime.now(timezone.utc))
                )
                logger.info("job.marked_timeout", job_id=str(job.id), created_at=str(job.created_at))
                await self.cache.invalidate(f"job:{job.id}:status")

            await db.commit()
