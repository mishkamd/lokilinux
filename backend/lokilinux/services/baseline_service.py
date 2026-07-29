"""
LokiLinux — BaselineService: scope-tree baselines, versioning, approval workflow.

Workflow: DRAFT -> PENDING_APPROVAL -> APPROVED -> PUBLISHED -> DEPRECATED.
Publish/rollback are the only transitions that touch which version is "live"
for a baseline (exactly one PUBLISHED version per baseline at a time).

ponytail: content_hash uses hashlib.sha256 over canonical (sorted-key) JSON,
not BLAKE3 — this hash lives in its own namespace (baseline content identity,
never compared against agent-computed domain hashes), so there is no
cross-language consistency requirement forcing BLAKE3 here. Ed25519 signing
(signature/signed_by) is deliberately left unset: docs/compliance/06-BASELINE.md
assigns signing to lokilinux-compliance (the Go service, not yet built —
02-GO-SERVICE.md), which is the only process meant to hold the private key.
Upgrade path: once that service exists, it signs on the same
COMPLIANCE_BASELINE_PUBLISHED event this method already publishes, and
backfills signature/signed_by — no API change needed here.
"""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.baseline import Baseline, BaselineApproval, BaselineVersion
from lokilinux.nats_topics import COMPLIANCE_BASELINE_PUBLISHED
from lokilinux.services.audit_service import AuditService


def _content_hash(expected_state: dict) -> str:
    canonical = json.dumps(expected_state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class BaselineService:
    def __init__(self, db: AsyncSession, nats=None) -> None:
        self.db = db
        self.nats = nats

    async def create_baseline(
        self,
        name: str,
        scope_type: str,
        scope_selector: dict,
        expected_state: dict,
        description: str | None = None,
        parent_baseline_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> Baseline:
        baseline = Baseline(
            name=name,
            description=description,
            scope_type=scope_type,
            scope_selector=scope_selector,
            parent_baseline_id=parent_baseline_id,
            created_by=created_by,
        )
        self.db.add(baseline)
        await self.db.flush()  # populate baseline.id before the version FK needs it

        version = BaselineVersion(
            baseline_id=baseline.id,
            version=1,
            status="DRAFT",
            expected_state=expected_state,
            content_hash=_content_hash(expected_state),
            created_by=created_by,
        )
        self.db.add(version)
        await self.db.commit()
        return baseline

    async def _get_version(self, version_id: UUID) -> BaselineVersion:
        row = (
            await self.db.execute(select(BaselineVersion).where(BaselineVersion.id == version_id))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Baseline version not found")
        return row

    async def create_version(
        self,
        baseline_id: UUID,
        expected_state: dict,
        change_summary: str | None,
        created_by: UUID | None,
    ) -> BaselineVersion:
        max_version = (
            await self.db.execute(
                select(func.max(BaselineVersion.version)).where(BaselineVersion.baseline_id == baseline_id)
            )
        ).scalar_one()
        if max_version is None:
            raise HTTPException(status_code=404, detail="Baseline not found")

        version = BaselineVersion(
            baseline_id=baseline_id,
            version=max_version + 1,
            status="DRAFT",
            expected_state=expected_state,
            content_hash=_content_hash(expected_state),
            change_summary=change_summary,
            created_by=created_by,
        )
        self.db.add(version)
        await self.db.commit()
        return version

    async def submit(self, version_id: UUID, actor: dict) -> BaselineVersion:
        version = await self._get_version(version_id)
        if version.status != "DRAFT":
            raise HTTPException(status_code=409, detail=f"Cannot submit from status {version.status}")
        version.status = "PENDING_APPROVAL"
        await self.db.commit()
        await AuditService(self.db).log(
            action="compliance.baseline_version_submitted",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="baseline_version",
            resource_id=str(version_id),
        )
        return version

    async def approve(self, version_id: UUID, actor: dict) -> BaselineVersion:
        version = await self._get_version(version_id)
        if version.status != "PENDING_APPROVAL":
            raise HTTPException(status_code=409, detail=f"Cannot approve from status {version.status}")

        approver_raw_id = actor.get("id")
        if approver_raw_id and version.created_by and str(version.created_by) == str(approver_raw_id):
            raise HTTPException(status_code=403, detail="Author cannot approve their own baseline version")

        approver_uuid = _safe_uuid(approver_raw_id)
        if approver_uuid is not None:
            self.db.add(
                BaselineApproval(
                    baseline_version_id=version_id,
                    approver_id=approver_uuid,
                    decision="APPROVED",
                )
            )
        version.status = "APPROVED"
        await self.db.commit()
        await AuditService(self.db).log(
            action="compliance.baseline_version_approved",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="baseline_version",
            resource_id=str(version_id),
        )
        return version

    async def publish(self, version_id: UUID, actor: dict) -> BaselineVersion:
        version = await self._get_version(version_id)
        if version.status != "APPROVED":
            raise HTTPException(status_code=409, detail=f"Cannot publish from status {version.status}")

        # Exactly one PUBLISHED version per baseline — deprecate the current one, if any.
        current = (
            await self.db.execute(
                select(BaselineVersion).where(
                    BaselineVersion.baseline_id == version.baseline_id,
                    BaselineVersion.status == "PUBLISHED",
                )
            )
        ).scalar_one_or_none()
        if current is not None:
            current.status = "DEPRECATED"
            current.deprecated_at = datetime.now(timezone.utc)

        version.status = "PUBLISHED"
        version.published_at = datetime.now(timezone.utc)
        version.deprecated_at = None
        await self.db.commit()

        if self.nats is not None:
            await self.nats.publish(
                COMPLIANCE_BASELINE_PUBLISHED,
                json.dumps({"baseline_id": str(version.baseline_id), "version_id": str(version_id)}).encode(),
            )
        await AuditService(self.db).log(
            action="compliance.baseline_version_published",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="baseline_version",
            resource_id=str(version_id),
        )
        return version

    async def rollback(self, version_id: UUID, actor: dict) -> BaselineVersion:
        """Re-publish an old DEPRECATED version. History is never mutated —
        this only flips which version is current, exactly like a forward
        publish (docs/compliance/06-BASELINE.md §5).
        """
        version = await self._get_version(version_id)
        if version.status != "DEPRECATED":
            raise HTTPException(status_code=409, detail="Rollback target must be a DEPRECATED version")

        current = (
            await self.db.execute(
                select(BaselineVersion).where(
                    BaselineVersion.baseline_id == version.baseline_id,
                    BaselineVersion.status == "PUBLISHED",
                )
            )
        ).scalar_one_or_none()
        if current is not None:
            current.status = "DEPRECATED"
            current.deprecated_at = datetime.now(timezone.utc)

        version.status = "PUBLISHED"
        version.published_at = datetime.now(timezone.utc)
        version.deprecated_at = None
        await self.db.commit()

        if self.nats is not None:
            await self.nats.publish(
                COMPLIANCE_BASELINE_PUBLISHED,
                json.dumps({"baseline_id": str(version.baseline_id), "version_id": str(version_id)}).encode(),
            )
        await AuditService(self.db).log(
            action="compliance.baseline_version_rolled_back",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="baseline_version",
            resource_id=str(version_id),
        )
        return version


def _safe_uuid(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None
