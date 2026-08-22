"""
LokiLinux — PolicySchedulerWorker: fires SCHEDULE-trigger policies whose
next_run_at has arrived.

Same shape as JobTimeoutWorker/HeartbeatMonitorWorker — its own asyncio loop,
no NATS event marks "a cron tick happened". Multiple API replicas would each
run one of these; the claim in _claim_and_run (an atomic UPDATE ... WHERE
next_run_at = <value we last saw>) is what stops two replicas from firing the
same policy twice, without needing NATS-KV leader election like the Go
compliance service uses for its own scheduler.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update

from lokilinux.models.policy import Policy
from lokilinux.models.workflow import Workflow
from lokilinux.services.policy_service import compute_next_run_at, run_policy

logger = structlog.get_logger()

_TICK_SECONDS = 30


class PolicySchedulerWorker:
    def __init__(self, db_session_factory, cache) -> None:
        self.db_factory = db_session_factory
        self.cache = cache
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("PolicySchedulerWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.error("policy_scheduler.tick_failed", exc_info=True)
            await asyncio.sleep(_TICK_SECONDS)

    async def _tick(self) -> None:
        async with self.db_factory() as db:
            now = datetime.now(timezone.utc)
            # Migration plan §15 stage C: a policy imported via
            # POST /policies/{id}/migrate (services/policy_migration.py)
            # has a Workflow row pointing back at it through
            # migrated_from_policy_id — WorkflowSchedulerWorker now owns its
            # cron, so this worker skips it rather than double-firing. No
            # extra column needed: the Workflow side already carries the
            # link, and this subquery is the one place anything reads it.
            migrated_policy_ids = select(Workflow.migrated_from_policy_id).where(Workflow.migrated_from_policy_id.isnot(None))
            due = (await db.execute(
                select(Policy).where(
                    Policy.is_enabled.is_(True),
                    Policy.trigger_type == "SCHEDULE",
                    Policy.next_run_at.isnot(None),
                    Policy.next_run_at <= now,
                    Policy.id.notin_(migrated_policy_ids),
                )
            )).scalars().all()

            for policy in due:
                await self._claim_and_run(db, policy)

    async def _claim_and_run(self, db, policy: Policy) -> None:
        seen_next_run_at = policy.next_run_at
        now = datetime.now(timezone.utc)
        try:
            new_next_run_at = compute_next_run_at(policy.cron_expr, now)
        except Exception:
            logger.error("policy_scheduler.invalid_cron", policy_id=str(policy.id), cron_expr=policy.cron_expr, exc_info=True)
            return

        result = await db.execute(
            update(Policy)
            .where(Policy.id == policy.id, Policy.next_run_at == seen_next_run_at)
            .values(next_run_at=new_next_run_at, last_run_at=now)
        )
        await db.commit()
        if result.rowcount != 1:
            return  # another replica already claimed this tick

        job_ids, matched = await run_policy(db, policy, self.cache, triggered_by="schedule")
        logger.info("policy.scheduled_run", policy_id=str(policy.id), matched_agents=matched, job_ids=[str(j) for j in job_ids])
