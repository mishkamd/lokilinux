"""
LokiLinux — RemediationService: plan workflow on top of the existing
Job Engine.

State machine:
  DRAFT → PENDING_APPROVAL → APPROVED → EXECUTING → COMPLETED / FAILED
                                                  → ROLLED_BACK (after rollback Job)

Maintenance-window aware: a plan with maintenance_window_id set stays
APPROVED (no Job created) until the scheduler worker dispatches it inside
an open window, unless is_emergency bypasses the wait.

Dedup, per-agent fan-out, and status aggregation are entirely JobService's;
this module never touches JobResult directly (docs/compliance/09-REMEDIATION.md).
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.drift import OPEN_DRIFT_STATUSES, DriftEvent
from lokilinux.models.remediation import (
    MaintenanceWindow,
    RemediationAction,
    RemediationJob,
    RemediationPlan,
)
from lokilinux.schemas.remediation import RemediationActionCreate
from lokilinux.services.audit_service import AuditService
from lokilinux.services.job_service import JobService


def build_actions_payload(actions: list[RemediationAction]) -> dict[str, list[dict]]:
    """Build the per-agent actions map for the Job parameters payload.

    Keys are str(agent_id); values are lists of action dicts sorted by
    sequence ascending. Only the fields the agent executor needs are
    included — no rule_id / drift_event_id / rollback_body at apply time.
    """
    by_agent: dict[str, list[dict]] = {}
    for a in sorted(actions, key=lambda a: a.sequence):
        entry = {
            "sequence": a.sequence,
            "provider": a.provider,
            "rendered_body": a.rendered_body,
        }
        by_agent.setdefault(str(a.agent_id), []).append(entry)
    return by_agent


class RemediationService:
    def __init__(self, db: AsyncSession, job_service: JobService) -> None:
        self.db = db
        self.job_service = job_service

    async def create_plan(
        self,
        name: str,
        trigger_type: str,
        actions: list[RemediationActionCreate],
        is_emergency: bool = False,
        maintenance_window_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> RemediationPlan:
        if not actions:
            raise HTTPException(status_code=400, detail="A remediation plan needs at least one action")

        from lokilinux.services.auto_remediation import is_monitor_only

        for a in actions:
            if a.rule_id is not None and await is_monitor_only(self.db, a.rule_id):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Rule {a.rule_id} is covered only by MONITOR-mode policies — "
                        "remediation is disabled for it (plan U7)"
                    ),
                )

        if maintenance_window_id is not None:
            window = await self.db.get(MaintenanceWindow, maintenance_window_id)
            if window is None or not window.is_enabled:
                raise HTTPException(
                    status_code=409,
                    detail="Referenced maintenance window does not exist or is disabled",
                )

        plan = RemediationPlan(
            name=name,
            trigger_type=trigger_type,
            is_emergency=is_emergency,
            maintenance_window_id=maintenance_window_id,
            created_by=created_by,
        )
        self.db.add(plan)
        await self.db.flush()

        for i, a in enumerate(actions):
            self.db.add(RemediationAction(
                remediation_plan_id=plan.id,
                rule_id=a.rule_id,
                drift_event_id=a.drift_event_id,
                agent_id=a.agent_id,
                provider=a.provider,
                rendered_body=a.rendered_body,
                rollback_body=a.rollback_body,
                sequence=i,
            ))
        await self.db.commit()
        return plan

    async def _get_plan(self, plan_id: UUID) -> RemediationPlan:
        plan = await self.db.get(RemediationPlan, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Remediation plan not found")
        return plan

    async def submit(self, plan_id: UUID, actor: dict) -> RemediationPlan:
        plan = await self._get_plan(plan_id)
        if plan.status != "DRAFT":
            raise HTTPException(status_code=409, detail=f"Cannot submit from status {plan.status}")
        plan.status = "PENDING_APPROVAL"
        await self.db.commit()
        await AuditService(self.db).log(
            action="compliance.remediation_plan_submitted", user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="remediation_plan", resource_id=str(plan_id),
        )
        return plan

    async def approve(self, plan_id: UUID, actor: dict) -> RemediationPlan:
        """Approve a plan and either dispatch immediately sau wait for window.

        - Emergency plans bypass the maintenance window.
        - Plans without a maintenance_window_id dispatch immediately.
        - Plans with a window that is currently open dispatch immediately.
        - Plans with a closed window commit as APPROVED; the scheduler
          worker dispatches them when the window opens.
        - Invalid/disabled window → 409, no Job created.
        """
        plan = await self._get_plan(plan_id)
        if plan.status != "PENDING_APPROVAL":
            raise HTTPException(status_code=409, detail=f"Cannot approve from status {plan.status}")

        approver_id = actor.get("id")
        plan.approved_by = _safe_uuid(approver_id)
        plan.approved_at = datetime.now(timezone.utc)

        # Validate window if referenced
        window: MaintenanceWindow | None = None
        if plan.maintenance_window_id is not None:
            window = await self.db.get(MaintenanceWindow, plan.maintenance_window_id)
            if window is None or not window.is_enabled:
                raise HTTPException(
                    status_code=409,
                    detail="Referenced maintenance window does not exist or is disabled",
                )

        # Decide: dispatch now or defer to scheduler
        should_dispatch = (
            plan.is_emergency
            or plan.maintenance_window_id is None
            or (window is not None and _is_window_open(window, datetime.now(timezone.utc)))
        )

        if should_dispatch:
            await self._dispatch(plan)
        else:
            plan.status = "APPROVED"
            await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.remediation_plan_approved", user_id=approver_id,
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="remediation_plan", resource_id=str(plan_id),
            changes={"dispatched": should_dispatch},
        )
        return plan

    async def _dispatch(self, plan: RemediationPlan) -> None:
        """Create the execution Job for a plan. Caller sets approved_by/at."""
        actions = (
            await self.db.execute(
                select(RemediationAction).where(RemediationAction.remediation_plan_id == plan.id)
            )
        ).scalars().all()
        agent_ids = sorted({str(a.agent_id) for a in actions})
        actions_map = build_actions_payload(actions)

        try:
            job = await self.job_service.create_job(
                name=f"Remediation: {plan.name}",
                job_type="COMPLIANCE_REMEDIATE",
                target_servers={"agent_ids": agent_ids},
                parameters={
                    "remediation_plan_id": str(plan.id),
                    "operation": "APPLY",
                    "actions": actions_map,
                },
                requires_approval=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        self.db.add(RemediationJob(remediation_plan_id=plan.id, job_id=job.id))
        plan.status = "EXECUTING"

        # Plan U6/incident wiring: an open drift incident this plan is
        # addressing shouldn't still read OPEN while a fix for it is
        # actually running — IN_REMEDIATION until the outcome is known
        # (verification COMPLETED resolves it; FAILED/ROLLED_BACK reverts
        # it, see job_service._sync_remediation_plan and
        # remediation_verification.py).
        drift_event_ids = [a.drift_event_id for a in actions if a.drift_event_id is not None]
        if drift_event_ids:
            await self.db.execute(
                update(DriftEvent)
                .where(
                    DriftEvent.id.in_(drift_event_ids),
                    DriftEvent.status.in_(OPEN_DRIFT_STATUSES),
                )
                .values(status="IN_REMEDIATION")
            )

        await self.db.commit()

    async def dry_run(self, plan_id: UUID, actor: dict) -> RemediationPlan:
        """Dispatch a DRY_RUN Job for the plan's actions — the agent runs
        each provider's real check mode (ansible --check --diff, sh -n,
        Python ast.parse) and reports results the same way an APPLY job
        does, but applies nothing. The plan's status is untouched
        (docs/compliance §13): dry-run is a preview, never a state
        transition — _sync_remediation_plan (job_service.py) explicitly
        skips DRY_RUN jobs for the same reason.
        """
        plan = await self._get_plan(plan_id)
        actions = (
            await self.db.execute(
                select(RemediationAction).where(RemediationAction.remediation_plan_id == plan.id)
            )
        ).scalars().all()
        if not actions:
            raise HTTPException(status_code=409, detail="Plan has no actions to dry-run")

        agent_ids = sorted({str(a.agent_id) for a in actions})
        actions_map = build_actions_payload(actions)

        try:
            job = await self.job_service.create_job(
                name=f"Remediation dry-run: {plan.name}",
                job_type="COMPLIANCE_REMEDIATE",
                target_servers={"agent_ids": agent_ids},
                parameters={
                    "remediation_plan_id": str(plan.id),
                    "operation": "DRY_RUN",
                    "actions": actions_map,
                },
                requires_approval=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        self.db.add(RemediationJob(remediation_plan_id=plan.id, job_id=job.id))
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.remediation_plan_dry_run",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="remediation_plan", resource_id=str(plan_id),
            changes={"job_id": str(job.id), "agent_count": len(agent_ids)},
        )
        return plan

    async def rollback(self, plan_id: UUID, actor: dict) -> RemediationPlan:
        """Roll back a completed/failed plan by dispatching a ROLLBACK Job.

        Only agents whose APPLY JobResult is COMPLETED and whose actions
        have a rollback_body are eligible. Actions are reversed
        (descending sequence) so undo order mirrors apply order.
        """
        plan = await self._get_plan(plan_id)
        if plan.status not in ("COMPLETED", "FAILED"):
            raise HTTPException(status_code=409, detail=f"Cannot rollback from status {plan.status}")

        from lokilinux.models.job import Job, JobResult
        from lokilinux.models.remediation import RemediationJob as RemediationJobLink

        # Find the most recent APPLY job for this plan
        links = (
            await self.db.execute(
                select(RemediationJobLink)
                .join(Job, Job.id == RemediationJobLink.job_id)
                .where(RemediationJobLink.remediation_plan_id == plan_id)
                .order_by(Job.created_at.desc())
            )
        ).scalars().all()

        apply_job_id: UUID | None = None
        for link in links:
            job = await self.db.get(Job, link.job_id)
            if job and (job.parameters or {}).get("operation", "APPLY") == "APPLY":
                apply_job_id = job.id
                break

        if apply_job_id is None:
            raise HTTPException(status_code=409, detail="No APPLY job found for this plan")

        # Get results for the apply job
        results = (
            await self.db.execute(
                select(JobResult).where(JobResult.job_id == apply_job_id, JobResult.status == "COMPLETED")
            )
        ).scalars().all()
        completed_agent_ids = {str(r.agent_id) for r in results}

        # Get actions with rollback_body for completed agents
        actions = (
            await self.db.execute(
                select(RemediationAction)
                .where(
                    RemediationAction.remediation_plan_id == plan_id,
                    RemediationAction.rollback_body.isnot(None),
                )
                .order_by(RemediationAction.sequence.desc())
            )
        ).scalars().all()

        # Filter to agents that completed, build rollback actions map
        rollback_map: dict[str, list[dict]] = {}
        seq = 0
        for a in actions:
            agent_key = str(a.agent_id)
            if agent_key not in completed_agent_ids:
                continue
            entry = {
                "sequence": seq,
                "provider": a.provider,
                "rendered_body": a.rollback_body,
            }
            rollback_map.setdefault(agent_key, []).append(entry)
            seq += 1

        if not rollback_map:
            raise HTTPException(
                status_code=409,
                detail="No completed reversible remediation actions",
            )

        agent_ids = sorted(rollback_map.keys())

        try:
            job = await self.job_service.create_job(
                name=f"Remediation rollback: {plan.name}",
                job_type="COMPLIANCE_REMEDIATE",
                target_servers={"agent_ids": agent_ids},
                parameters={
                    "remediation_plan_id": str(plan.id),
                    "operation": "ROLLBACK",
                    "actions": rollback_map,
                },
                requires_approval=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        self.db.add(RemediationJob(remediation_plan_id=plan.id, job_id=job.id))
        plan.status = "EXECUTING"
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.remediation_plan_rollback_started",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="remediation_plan", resource_id=str(plan_id),
            changes={"job_id": str(job.id), "agent_count": len(agent_ids)},
        )
        return plan


def _is_window_open(window: MaintenanceWindow, now: datetime) -> bool:
    """Check whether a maintenance window is currently open.

    Converts `now` to the window's timezone, finds the last cron
    occurrence <= now, and considers the window open in the interval
    [occurrence, occurrence + duration_minutes].
    """
    if not window.cron_expr:
        return False
    try:
        from croniter import croniter
        import zoneinfo
        tz = zoneinfo.ZoneInfo(window.timezone)
        local_now = now.astimezone(tz)
        cron = croniter(window.cron_expr, local_now)
        # Get the previous occurrence (including now if it matches exactly)
        prev = cron.get_prev(datetime)
        # croniter returns a naive datetime; attach the window's tz
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=tz)
        from datetime import timedelta
        window_end = prev + timedelta(minutes=window.duration_minutes)
        return prev <= local_now <= window_end
    except Exception:
        return False


def agent_matches_window_scope(
    agent_os_distro: str | None,
    agent_os_version: str | None,
    agent_tags: dict,
    agent_custom_facts: dict,
    category_name: str | None,
    project_name: str | None,
    window: MaintenanceWindow,
) -> bool:
    """Check whether an agent matches a maintenance window's scope.

    GLOBAL with empty/{"all": true} selector matches any agent.
    For other scope types, compares selector keys against agent attributes.
    All selector keys must match (AND logic).
    """
    scope = window.scope_type
    selector = window.scope_selector or {}

    if scope == "GLOBAL":
        if not selector or selector.get("all") is True:
            return True
        return False

    if scope == "OS":
        distro_match = selector.get("distro") == agent_os_distro
        version_match = selector.get("version") is None or selector.get("version") == agent_os_version
        return distro_match and version_match

    if scope == "ROLE":
        role = selector.get("role")
        if not role:
            return False
        agent_roles = agent_tags.get("roles", [])
        return role in agent_roles

    if scope == "ENVIRONMENT":
        env = selector.get("environment")
        return env is not None and category_name == env

    if scope == "DATACENTER":
        dc = selector.get("datacenter")
        if not dc:
            return False
        agent_dc = agent_custom_facts.get("datacenter") or agent_tags.get("datacenter")
        return agent_dc == dc

    if scope == "CLUSTER":
        cluster = selector.get("cluster")
        if not cluster:
            return False
        agent_cluster = agent_custom_facts.get("cluster") or agent_tags.get("cluster")
        return agent_cluster == cluster

    if scope == "APPLICATION":
        app = selector.get("application")
        return app is not None and project_name == app

    return False


def _safe_uuid(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None
