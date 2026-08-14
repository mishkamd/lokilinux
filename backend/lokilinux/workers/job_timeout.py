"""
LokiLinux — JobTimeoutWorker: expire stale non-terminal jobs.

Runs its own asyncio loop (same shape as HeartbeatMonitorWorker — no NATS
event marks "this job has been stuck too long"). A Job left in
QUEUED/SCHEDULED/PENDING/RUNNING (agent dead, or executing a binary built
before the job type it was assigned existed) never transitions out on its
own, and JobService.create_job's dedup_key check treats any such job as
"active" forever — blocking every future identical job with a 409 that never
clears. Sweeping stale jobs into TIMEOUT frees the dedup key and surfaces the
real state in the UI instead of eternal QUEUED.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update

from lokilinux.models.job import Job, JobResult, JobStatus
from lokilinux.settings_schema import get_setting_value

logger = structlog.get_logger()

_SWEEP_INTERVAL_SECONDS = 60
_NON_TERMINAL = (JobStatus.QUEUED, JobStatus.SCHEDULED, JobStatus.PENDING, JobStatus.RUNNING)


class JobTimeoutWorker:
    def __init__(self, db_session_factory, cache) -> None:
        self.db_factory = db_session_factory
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

            now = datetime.now(timezone.utc)
            for job in stale:
                job.status = JobStatus.TIMEOUT
                if job.completed_at is None:
                    job.completed_at = now

                await db.execute(
                    update(JobResult)
                    .where(JobResult.job_id == job.id, JobResult.status.in_(("PENDING", "RUNNING")))
                    .values(status="TIMEOUT", completed_at=now)
                )
                logger.info("job.marked_timeout", job_id=str(job.id), created_at=str(job.created_at))

            await db.commit()

            # Sync remediation plans for timed-out jobs
            from lokilinux.services.job_service import sync_remediation_plan
            for job in stale:
                if job.job_type == "COMPLIANCE_REMEDIATE":
                    await sync_remediation_plan(db, job.id)
            await db.commit()

            for job in stale:
                await self.cache.invalidate(f"job:{job.id}:status")
