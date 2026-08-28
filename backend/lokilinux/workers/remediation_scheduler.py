"""
LokiLinux — RemediationSchedulerWorker: dispatches APPROVED remediation
plans whose maintenance window is currently open, and (Enterprise
Compliance plan U7/KTD8, Autopilot A2) drives the AUTOMATIC-mode closed
loop: finding -> plan -> mandatory dry-run -> auto-approve -> dispatch.
Verification/resolution after dispatch is already generic (job_service.py's
_sync_remediation_plan + RemediationVerificationWorker don't branch on
trigger_type) — this worker only owns the part before a plan reaches
EXECUTING.

Same shape as PolicySchedulerWorker — its own asyncio loop, no NATS event
marks "a cron tick happened". Multiple API replicas would each run one;
the claim in _dispatch_plan (an atomic status check before Job creation)
plus JobService's dedup key prevent double-dispatch across replicas.
"""

import asyncio
import contextlib
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from lokilinux.models.agent import Agent
from lokilinux.models.category import Category, Project
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.drift import OPEN_DRIFT_STATUSES, DriftEvent
from lokilinux.models.job import Job, JobStatus
from lokilinux.models.remediation import RemediationAction, RemediationJob, RemediationPlan
from lokilinux.schemas.remediation import RemediationActionCreate
from lokilinux.services.audit_service import AuditService
from lokilinux.services.auto_remediation import (
    already_attempted_today,
    eligible_for_automatic,
    find_active_template,
    find_automatic_candidates,
    find_open_window,
    plans_created_today,
)
from lokilinux.services.job_service import JobService
from lokilinux.services.remediation_service import (
    RemediationService,
    _is_window_open,
    agent_matches_window_scope,
)
from lokilinux.settings_schema import get_setting_value

logger = structlog.get_logger()

_AUTOPILOT_ACTOR = {"id": None, "username": "system:autopilot"}
_TICK_SECONDS = 30
# A DRAFT AUTOMATIC plan with no dry-run job linked yet after this long
# means the dispatch itself crashed between create_plan and dry_run — not
# a real dry-run in flight. Fail it instead of leaving it stuck forever.
_DRY_RUN_DISPATCH_GRACE = 300


class RemediationSchedulerWorker:
    def __init__(self, db_session_factory, cache, nats) -> None:
        self.db_factory = db_session_factory
        self.cache = cache
        self.nats = nats
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("RemediationSchedulerWorker started")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.error("remediation_scheduler.tick_failed", exc_info=True)
            await asyncio.sleep(_TICK_SECONDS)

    async def _tick(self) -> None:
        async with self.db_factory() as db:
            now = datetime.now(timezone.utc)

            # Find APPROVED plans with a maintenance_window_id
            plans = (
                await db.execute(
                    select(RemediationPlan).where(
                        RemediationPlan.status == "APPROVED",
                        RemediationPlan.maintenance_window_id.isnot(None),
                    )
                )
            ).scalars().all()

            for plan in plans:
                await self._try_dispatch(db, plan, now)

            await self._tick_automatic(db, now)

    async def _try_dispatch(self, db, plan: RemediationPlan, now: datetime) -> None:
        """Dispatch a plan if its maintenance window is open and all agents match scope."""
        from lokilinux.models.remediation import MaintenanceWindow

        window = await db.get(MaintenanceWindow, plan.maintenance_window_id)
        if window is None or not window.is_enabled:
            logger.warning(
                "remediation_scheduler.invalid_window",
                plan_id=str(plan.id),
                window_id=str(plan.maintenance_window_id),
            )
            return

        if not _is_window_open(window, now):
            return  # window not open yet, plan stays APPROVED

        # Check all agents match the window scope
        actions = (
            await db.execute(
                select(RemediationAction).where(RemediationAction.remediation_plan_id == plan.id)
            )
        ).scalars().all()

        agent_ids = {a.agent_id for a in actions}
        if not agent_ids:
            return

        agents = (
            await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        ).scalars().all()

        found_agent_ids = {agent.id for agent in agents}
        if found_agent_ids != agent_ids:
            logger.warning(
                "remediation_scheduler.missing_agents",
                plan_id=str(plan.id),
                missing_agent_ids=[str(agent_id) for agent_id in agent_ids - found_agent_ids],
            )
            return  # a target no longer exists, plan stays APPROVED

        # Load category/project names for scope matching
        category_ids = {a.category_id for a in agents if a.category_id}
        project_ids = {a.project_id for a in agents if a.project_id}

        categories = {}
        if category_ids:
            cat_rows = (
                await db.execute(select(Category).where(Category.id.in_(category_ids)))
            ).scalars().all()
            categories = {c.id: c.name for c in cat_rows}

        projects = {}
        if project_ids:
            proj_rows = (
                await db.execute(select(Project).where(Project.id.in_(project_ids)))
            ).scalars().all()
            projects = {p.id: p.name for p in proj_rows}

        # Check all agents match scope
        for agent in agents:
            if not agent_matches_window_scope(
                agent_os_distro=agent.os_distro,
                agent_os_version=agent.os_version,
                agent_tags=agent.tags or {},
                agent_custom_facts=agent.custom_facts or {},
                category_name=categories.get(agent.category_id),
                project_name=projects.get(agent.project_id),
                window=window,
            ):
                logger.info(
                    "remediation_scheduler.agent_scope_mismatch",
                    plan_id=str(plan.id),
                    agent_id=str(agent.id),
                )
                return  # not all agents match, plan stays APPROVED

        # All agents match, dispatch
        logger.info(
            "remediation_scheduler.dispatching",
            plan_id=str(plan.id),
            agent_count=len(agent_ids),
        )
        svc = RemediationService(db, JobService(db, self.cache, self.nats))
        try:
            await svc._dispatch(plan)
        except Exception:
            logger.error("remediation_scheduler.dispatch_failed", plan_id=str(plan.id), exc_info=True)

    # ── AUTOMATIC mode (plan U7/KTD8, Autopilot A2) ─────────────────────────

    async def _tick_automatic(self, db, now: datetime) -> None:
        if not await get_setting_value(db, "compliance.auto_remediation_enabled"):
            return
        await self._resolve_pending_dry_runs(db, now)
        await self._trigger_new_automatic_plans(db, now)

    async def _latest_dry_run_job(self, db, plan_id) -> Job | None:
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
        if job is None or (job.parameters or {}).get("operation") != "DRY_RUN":
            return None
        return job

    async def _resolve_pending_dry_runs(self, db, now: datetime) -> None:
        """AUTOMATIC plans stay DRAFT while their mandatory dry-run job runs
        (job_service.py's _sync_remediation_plan deliberately never touches
        plan.status for DRY_RUN jobs — that generic rule serves the manual
        preview flow too). This is the AUTOMATIC-specific half: a completed
        dry-run graduates DRAFT -> PENDING_APPROVAL -> (auto-approved,
        dispatched if the window's still open) or FAILS the plan outright,
        never silently retrying."""
        plans = (
            await db.execute(
                select(RemediationPlan).where(
                    RemediationPlan.status == "DRAFT", RemediationPlan.trigger_type == "AUTOMATIC"
                )
            )
        ).scalars().all()
        if not plans:
            return

        svc = RemediationService(db, JobService(db, self.cache, self.nats))
        for plan in plans:
            job = await self._latest_dry_run_job(db, plan.id)
            if job is None:
                if (now - plan.created_at).total_seconds() > _DRY_RUN_DISPATCH_GRACE:
                    await self._fail_automatic_plan(db, plan, "dry-run job never dispatched")
                continue

            if job.status not in (
                JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED,
            ):
                continue  # still running, check again next tick

            if job.status != JobStatus.COMPLETED:
                await self._fail_automatic_plan(db, plan, f"dry-run {job.status.value.lower()}")
                continue

            logger.info("remediation_scheduler.automatic_dry_run_passed", plan_id=str(plan.id))
            try:
                await svc.submit(plan.id, _AUTOPILOT_ACTOR)
                await svc.approve(plan.id, _AUTOPILOT_ACTOR)
            except Exception:
                logger.error(
                    "remediation_scheduler.automatic_approve_failed",
                    plan_id=str(plan.id),
                    exc_info=True,
                )

    async def _fail_automatic_plan(self, db, plan: RemediationPlan, reason: str) -> None:
        plan.status = "FAILED"
        await AuditService(db).log(
            action="compliance.remediation_plan_auto_failed",
            actor_type="system",
            actor_name=_AUTOPILOT_ACTOR["username"],
            resource_type="remediation_plan",
            resource_id=str(plan.id),
            changes={"reason": reason},
        )
        logger.warning(
            "remediation_scheduler.automatic_plan_failed", plan_id=str(plan.id), reason=reason
        )

    async def _trigger_new_automatic_plans(self, db, now: datetime) -> None:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cap = await get_setting_value(db, "compliance.auto_remediation_max_plans_per_day")
        remaining = cap - await plans_created_today(db, today_start)
        if remaining <= 0:
            return

        candidates = await find_automatic_candidates(db)
        svc = RemediationService(db, JobService(db, self.cache, self.nats))

        for c in candidates:
            if remaining <= 0:
                break
            agent_id, rule, policy = c["agent_id"], c["rule"], c["policy"]

            if await already_attempted_today(db, agent_id, rule.id, today_start):
                continue

            eligible, reason = await eligible_for_automatic(db, agent_id, rule, policy)
            if not eligible:
                logger.debug(
                    "remediation_scheduler.automatic_not_eligible",
                    agent_id=str(agent_id), rule_id=str(rule.id), reason=reason,
                )
                continue

            try:
                await self._create_automatic_plan(db, svc, agent_id, rule)
                remaining -= 1
            except Exception:
                logger.error(
                    "remediation_scheduler.automatic_create_failed",
                    agent_id=str(agent_id), rule_id=str(rule.id), exc_info=True,
                )

    async def _create_automatic_plan(
        self, db, svc: RemediationService, agent_id, rule: ComplianceRule
    ) -> None:
        # Re-fetches Agent/template/window rather than threading them through
        # from eligible_for_automatic (which only returns bool+reason) —
        # cheap: the session's identity map already has Agent loaded, and
        # template/window are single indexed lookups.
        agent = await db.get(Agent, agent_id)
        template = await find_active_template(db, rule.rule_key)
        window = await find_open_window(db, agent)
        if agent is None or template is None or window is None:
            return  # eligibility flipped between the check above and here — try again next tick

        open_drift_id = (
            await db.execute(
                select(DriftEvent.id)
                .where(
                    DriftEvent.agent_id == agent_id,
                    DriftEvent.domain == rule.domain,
                    DriftEvent.status.in_(OPEN_DRIFT_STATUSES),
                )
                .order_by(DriftEvent.time.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        plan = await svc.create_plan(
            name=f"Auto-remediate {rule.rule_key} on {agent.hostname or agent.agent_id}",
            trigger_type="AUTOMATIC",
            actions=[
                RemediationActionCreate(
                    agent_id=agent_id,
                    rule_id=rule.id,
                    drift_event_id=open_drift_id,
                    provider=template.provider,
                    rendered_body=template.body,
                    rollback_body=template.rollback_body,
                )
            ],
            maintenance_window_id=window.id,
            created_by=None,
        )
        await AuditService(db).log(
            action="compliance.remediation_plan_auto_triggered",
            actor_type="system",
            actor_name=_AUTOPILOT_ACTOR["username"],
            resource_type="remediation_plan",
            resource_id=str(plan.id),
            changes={"rule_key": rule.rule_key, "agent_id": str(agent_id)},
        )

        await svc.dry_run(plan.id, _AUTOPILOT_ACTOR)
        logger.info(
            "remediation_scheduler.automatic_plan_created",
            plan_id=str(plan.id), rule_key=rule.rule_key, agent_id=str(agent_id),
        )
