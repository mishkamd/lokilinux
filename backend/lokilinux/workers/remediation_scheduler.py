"""
LokiLinux — RemediationSchedulerWorker: dispatches APPROVED remediation
plans whose maintenance window is currently open.

Same shape as PolicySchedulerWorker — its own asyncio loop, no NATS event
marks "a cron tick happened". Multiple API replicas would each run one;
the claim in _dispatch_plan (an atomic status check before Job creation)
plus JobService's dedup key prevent double-dispatch across replicas.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from lokilinux.models.agent import Agent
from lokilinux.models.category import Category, Project
from lokilinux.models.remediation import RemediationAction, RemediationPlan
from lokilinux.services.job_service import JobService
from lokilinux.services.remediation_service import (
    RemediationService,
    _is_window_open,
    agent_matches_window_scope,
)

logger = structlog.get_logger()

_TICK_SECONDS = 30


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
        if self._task:
            self._task.cancel()

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

            if not plans:
                return

            for plan in plans:
                await self._try_dispatch(db, plan, now)

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
