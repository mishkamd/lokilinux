"""
LokiLinux — ExceptionService: create/approve/revoke compliance exceptions
(waivers), docs/compliance §17.

A new exception starts PENDING — it only starts waiving FAIL verdicts once
approved (status ACTIVE). Expiry to EXPIRED is a background job
(services/compliance/internal/scheduler.Expirer), not this service; the
evaluation engine (services/compliance/internal/ingest) reads status='ACTIVE'
AND expires_at > now() directly, so there's no code path here that would let
a stale PENDING or EXPIRED row silently keep waiving anything.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_exception import ComplianceException
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.drift import OPEN_DRIFT_STATUSES, DriftEvent
from lokilinux.services.audit_service import AuditService


class ExceptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        rule_id: UUID,
        reason: str,
        owner: str,
        expires_at: datetime,
        agent_id: UUID | None,
        scope_selector: dict[str, Any],
        requested_by: UUID | None,
        actor: dict,
    ) -> ComplianceException:
        exc = ComplianceException(
            rule_id=rule_id,
            agent_id=agent_id,
            scope_selector=scope_selector or {},
            reason=reason,
            owner=owner,
            requested_by=requested_by,
            status="PENDING",
            expires_at=expires_at,
        )
        self.db.add(exc)
        await self.db.commit()
        await self.db.refresh(exc)

        await AuditService(self.db).log(
            action="compliance.exception_created",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="compliance_exception",
            resource_id=str(exc.id),
            changes={"rule_id": str(rule_id), "reason": reason, "expires_at": expires_at.isoformat()},
        )
        return exc

    async def approve(self, exc: ComplianceException, actor: dict, actor_id: UUID | None) -> ComplianceException:
        if exc.status != "PENDING":
            raise HTTPException(status_code=409, detail=f"Cannot approve from status {exc.status}")
        if exc.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="Cannot approve an exception whose expiry is already in the past")

        exc.status = "ACTIVE"
        exc.approved_by = actor_id
        exc.approved_at = datetime.now(timezone.utc)
        exc.updated_at = datetime.now(timezone.utc)
        await self._close_covered_drift(exc, actor_id)
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.exception_approved",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="compliance_exception",
            resource_id=str(exc.id),
            changes={"rule_id": str(exc.rule_id)},
        )
        return exc

    async def _close_covered_drift(self, exc: ComplianceException, actor_id: UUID | None) -> None:
        """Plan U6/incident wiring: an approved exception waives FAIL
        verdicts for its rule going forward (the evaluation engine already
        does this) — but any drift incident already OPEN on that same
        domain, for the agent(s) this exception covers, is now silently
        wrong to leave OPEN. Closes it as EXCEPTION instead. Expiry later
        (services/compliance scheduler.Expirer) does NOT reopen this row —
        a still-failing rule creates a fresh incident on its next snapshot,
        which is the existing (and correct) dedup behavior."""
        rule = await self.db.get(ComplianceRule, exc.rule_id)
        if rule is None:
            return
        q = update(DriftEvent).where(
            DriftEvent.domain == rule.domain, DriftEvent.status.in_(OPEN_DRIFT_STATUSES)
        )
        if exc.agent_id is not None:
            q = q.where(DriftEvent.agent_id == exc.agent_id)
        elif exc.scope_selector:
            # ponytail: fleet-wide exceptions narrowed by scope_selector
            # (tags/category/environment) need agent-attribute matching
            # that only exists Go-side (services/compliance/internal/scope)
            # today — no Python equivalent to reuse. Add one when a real
            # exception needs it rather than guessing a matcher here.
            return
        # else: agent_id is None and scope_selector is empty — a genuinely
        # fleet-wide exception, matches every open incident on the domain.
        await self.db.execute(q.values(status="EXCEPTION", suppressed_by=actor_id))

    async def revoke(self, exc: ComplianceException, actor: dict) -> ComplianceException:
        if exc.status not in ("PENDING", "ACTIVE"):
            raise HTTPException(status_code=409, detail=f"Cannot revoke from status {exc.status}")

        exc.status = "REVOKED"
        exc.updated_at = datetime.now(timezone.utc)
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.exception_revoked",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="compliance_exception",
            resource_id=str(exc.id),
            changes={"rule_id": str(exc.rule_id)},
        )
        return exc
