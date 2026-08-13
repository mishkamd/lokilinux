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

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_exception import ComplianceException
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
        if exc.expires_at <= datetime.utcnow():
            raise HTTPException(status_code=409, detail="Cannot approve an exception whose expiry is already in the past")

        exc.status = "ACTIVE"
        exc.approved_by = actor_id
        exc.approved_at = datetime.utcnow()
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

    async def revoke(self, exc: ComplianceException, actor: dict) -> ComplianceException:
        if exc.status not in ("PENDING", "ACTIVE"):
            raise HTTPException(status_code=409, detail=f"Cannot revoke from status {exc.status}")

        exc.status = "REVOKED"
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
