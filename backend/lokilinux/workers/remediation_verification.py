"""
LokiLinux — RemediationVerificationWorker: closes the loop on VERIFYING
remediation plans (docs/compliance §14).

_sync_remediation_plan (services/job_service.py) moves a plan to VERIFYING
once its APPLY job's agent-side exit code is COMPLETED — but an exit code
only means the commands ran without error, never that the desired state
actually holds. This worker re-checks: for every (agent_id, rule_id) the
plan's actions touched, has a *fresh* rule_evaluations row (timestamped
after the APPLY job finished) landed, and is it PASS? That fresh row comes
from the compliance engine's normal pipeline — either the incremental
FIM-triggered re-evaluation (services/compliance/internal/ingest, F3) if the
remediated resource is a monitored file, or the domain's next natural
snapshot otherwise. This worker never evaluates anything itself; it only
reads what the Go service already wrote.

Same shape as RemediationSchedulerWorker — its own asyncio loop, tick-based.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text

from lokilinux.models.job import Job
from lokilinux.models.remediation import RemediationAction, RemediationJob, RemediationPlan
from lokilinux.services.audit_service import AuditService

logger = structlog.get_logger()

_TICK_SECONDS = 30
# A plan stuck in VERIFYING this long without every action's rule producing
# a fresh verdict is treated as a failure, not left hanging forever — the
# agent may be offline, or the remediated resource may not be monitored by
# anything that would ever re-evaluate it on its own.
_VERIFICATION_TIMEOUT = timedelta(minutes=15)


class RemediationVerificationWorker:
    def __init__(self, db_session_factory) -> None:
        self.db_factory = db_session_factory
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("RemediationVerificationWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.error("remediation_verification.tick_failed", exc_info=True)
            await asyncio.sleep(_TICK_SECONDS)

    async def _tick(self) -> None:
        async with self.db_factory() as db:
            plans = (
                await db.execute(select(RemediationPlan).where(RemediationPlan.status == "VERIFYING"))
            ).scalars().all()
            for plan in plans:
                await self._verify_plan(db, plan)

    async def _verify_plan(self, db, plan: RemediationPlan) -> None:
        apply_job = await self._latest_apply_job(db, plan.id)
        if apply_job is None or apply_job.completed_at is None:
            return  # shouldn't happen — _sync_remediation_plan only sets VERIFYING after a terminal APPLY job

        actions = (
            await db.execute(
                select(RemediationAction).where(
                    RemediationAction.remediation_plan_id == plan.id,
                    RemediationAction.rule_id.isnot(None),
                )
            )
        ).scalars().all()
        pairs = {(a.agent_id, a.rule_id) for a in actions}
        if not pairs:
            plan.status = "COMPLETED"
            await db.commit()
            return

        verdicts: dict[tuple, str | None] = {}
        for agent_id, rule_id in pairs:
            verdicts[(agent_id, rule_id)] = await self._latest_fresh_result(
                db, agent_id, rule_id, apply_job.completed_at
            )

        if all(v == "PASS" for v in verdicts.values()):
            plan.status = "COMPLETED"
            await self._resolve_related_drift(db, pairs)
            await AuditService(db).log(
                action="compliance.remediation_plan_verified",
                resource_type="remediation_plan",
                resource_id=str(plan.id),
                changes={"result": "PASS", "checked": len(pairs)},
            )
            await db.commit()
            return

        if any(v == "FAIL" for v in verdicts.values()):
            plan.status = "FAILED"
            await AuditService(db).log(
                action="compliance.remediation_plan_verification_failed",
                resource_type="remediation_plan",
                resource_id=str(plan.id),
                changes={
                    "failed_pairs": [
                        {"agent_id": str(a), "rule_id": str(r)} for (a, r), v in verdicts.items() if v == "FAIL"
                    ]
                },
            )
            await db.commit()
            return

        # No fresh verdict yet for at least one pair — still waiting, unless
        # we've been waiting too long.
        if datetime.now(timezone.utc) - apply_job.completed_at > _VERIFICATION_TIMEOUT:
            plan.status = "FAILED"
            await AuditService(db).log(
                action="compliance.remediation_plan_verification_timeout",
                resource_type="remediation_plan",
                resource_id=str(plan.id),
            )
            await db.commit()

    async def _latest_apply_job(self, db, plan_id) -> Job | None:
        link = (
            await db.execute(
                select(RemediationJob)
                .join(Job, Job.id == RemediationJob.job_id)
                .where(RemediationJob.remediation_plan_id == plan_id)
                .order_by(Job.created_at.desc())
            )
        ).scalars().first()
        if link is None:
            return None
        job = await db.get(Job, link.job_id)
        if job is None or (job.parameters or {}).get("operation", "APPLY") != "APPLY":
            return None
        return job

    async def _latest_fresh_result(self, db, agent_id, rule_id, since: datetime) -> str | None:
        """Latest rule_evaluations.result for (agent_id, rule_id) with
        time > since, or None if nothing has landed yet. Raw SQL against the
        hypertable — same convention dashboard.py already uses for reading
        this table from Python."""
        row = (
            await db.execute(
                text(
                    """
                    SELECT result FROM rule_evaluations
                    WHERE agent_id = :agent_id AND rule_id = :rule_id AND time > :since
                    ORDER BY time DESC LIMIT 1
                    """
                ),
                {"agent_id": agent_id, "rule_id": rule_id, "since": since},
            )
        ).first()
        return row[0] if row else None

    async def _resolve_related_drift(self, db, pairs: set[tuple]) -> None:
        """Closes OPEN/ACKNOWLEDGED/IN_REMEDIATION drift for the domains a
        verified-PASS remediation touched — the underlying config is now
        confirmed correct, so any open incident on that (agent, domain) is
        resolved rather than left dangling until it separately expires."""
        for agent_id, rule_id in pairs:
            await db.execute(
                text(
                    """
                    UPDATE drift_events SET status = 'RESOLVED', resolved_at = now()
                    WHERE agent_id = :agent_id
                      AND status IN ('OPEN', 'ACKNOWLEDGED', 'IN_REMEDIATION')
                      AND domain = (SELECT domain FROM compliance_rules WHERE id = :rule_id)
                    """
                ),
                {"agent_id": agent_id, "rule_id": rule_id},
            )
