"""
LokiLinux — RemediationService: plan workflow on top of the existing
Job Engine.

DRAFT -> PENDING_APPROVAL -> APPROVED+EXECUTING (approval and Job creation
happen atomically — a separate "publish" step would let a plan sit approved
but never actually dispatched, which is worse than combining the two).
Dedup, per-agent fan-out, and status aggregation are entirely JobService's;
this module never touches JobResult directly (docs/compliance/09-REMEDIATION.md).
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.remediation import RemediationAction, RemediationJob, RemediationPlan
from lokilinux.schemas.remediation import RemediationActionCreate
from lokilinux.services.audit_service import AuditService
from lokilinux.services.job_service import JobService


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
        created_by: UUID | None = None,
    ) -> RemediationPlan:
        if not actions:
            raise HTTPException(status_code=400, detail="A remediation plan needs at least one action")

        plan = RemediationPlan(name=name, trigger_type=trigger_type, is_emergency=is_emergency, created_by=created_by)
        self.db.add(plan)
        await self.db.flush()

        for i, a in enumerate(actions):
            self.db.add(RemediationAction(
                remediation_plan_id=plan.id, rule_id=a.rule_id, drift_event_id=a.drift_event_id,
                agent_id=a.agent_id, provider=a.provider, rendered_body=a.rendered_body,
                rollback_body=a.rollback_body, sequence=i,
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
        """Approve and immediately dispatch — creates the real Job via the
        existing JobService, fanning out one JobResult per targeted agent.
        Emergency plans skip nothing here except the maintenance-window
        wait (not yet implemented); approval is never bypassed."""
        plan = await self._get_plan(plan_id)
        if plan.status != "PENDING_APPROVAL":
            raise HTTPException(status_code=409, detail=f"Cannot approve from status {plan.status}")

        actions = (
            await self.db.execute(
                select(RemediationAction).where(RemediationAction.remediation_plan_id == plan_id)
            )
        ).scalars().all()
        agent_ids = sorted({str(a.agent_id) for a in actions})

        approver_id = actor.get("id")
        try:
            job = await self.job_service.create_job(
                name=f"Remediation: {plan.name}",
                job_type="COMPLIANCE_REMEDIATE",
                target_servers={"agent_ids": agent_ids},
                parameters={"remediation_plan_id": str(plan_id)},
                requires_approval=False,  # already approved at the plan level — no double gate
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        self.db.add(RemediationJob(remediation_plan_id=plan_id, job_id=job.id))
        plan.status = "EXECUTING"
        plan.approved_by = _safe_uuid(approver_id)
        plan.approved_at = datetime.now(timezone.utc)
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.remediation_plan_approved", user_id=approver_id,
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="remediation_plan", resource_id=str(plan_id),
            changes={"job_id": str(job.id), "agent_count": len(agent_ids)},
        )
        return plan


def _safe_uuid(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None
