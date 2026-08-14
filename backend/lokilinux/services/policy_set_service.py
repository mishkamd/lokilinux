"""
LokiLinux — PolicySetService: draft/publish/archive lifecycle + flat
immutable versioning for policy sets (docs/compliance §6).

Workflow: DRAFT -> PUBLISHED -> ARCHIVED. Unlike baselines (a second
BaselineVersion table per baseline), policy_sets uses flat versioning
(migration 025): a PUBLISHED set is edited by cloning a new DRAFT row via
parent_policy_set_id, never by mutating rules under an already-published
set — publishing the clone is what makes the edit live, and the old
published row stays intact and queryable exactly as it was distributed.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_rule import PolicySet, PolicySetRule
from lokilinux.services.audit_service import AuditService


class PolicySetService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get(self, policy_set_id: UUID) -> PolicySet:
        row = (await self.db.execute(select(PolicySet).where(PolicySet.id == policy_set_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Policy set not found")
        return row

    async def create_draft(
        self,
        name: str,
        slug: str,
        framework: str,
        version: str | None,
        description: str | None,
    ) -> PolicySet:
        existing = (await self.db.execute(select(PolicySet).where(PolicySet.slug == slug))).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Policy set slug '{slug}' already exists")
        policy_set = PolicySet(
            name=name, slug=slug, framework=framework, version=version, description=description,
            status="DRAFT", published_version=1, is_enabled=False,
        )
        self.db.add(policy_set)
        await self.db.commit()
        return policy_set

    async def publish(self, policy_set_id: UUID, actor: dict) -> PolicySet:
        policy_set = await self._get(policy_set_id)
        if policy_set.status != "DRAFT":
            raise HTTPException(status_code=409, detail=f"Cannot publish from status {policy_set.status}")

        rule_count = (
            await self.db.execute(select(PolicySetRule).where(PolicySetRule.policy_set_id == policy_set_id))
        ).scalars().first()
        if rule_count is None:
            raise HTTPException(status_code=409, detail="Cannot publish a policy set with no rules")

        policy_set.status = "PUBLISHED"
        policy_set.published_at = datetime.now(timezone.utc)
        policy_set.is_enabled = True
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.policy_set_published",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="policy_set",
            resource_id=str(policy_set_id),
            changes={"published_version": policy_set.published_version},
        )
        return policy_set

    async def archive(self, policy_set_id: UUID, actor: dict) -> PolicySet:
        policy_set = await self._get(policy_set_id)
        if policy_set.status != "PUBLISHED":
            raise HTTPException(status_code=409, detail=f"Cannot archive from status {policy_set.status}")

        policy_set.status = "ARCHIVED"
        policy_set.is_enabled = False
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.policy_set_archived",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="policy_set",
            resource_id=str(policy_set_id),
        )
        return policy_set

    async def create_new_version(self, policy_set_id: UUID, actor: dict) -> PolicySet:
        """Clones a PUBLISHED policy set into a new DRAFT row so its rules
        can be edited — the published row is never mutated in place
        (docs/compliance §6: "A published policy version must be immutable.
        Changing it creates a new version.")."""
        published = await self._get(policy_set_id)
        if published.status != "PUBLISHED":
            raise HTTPException(status_code=409, detail="Can only create a new version from a PUBLISHED policy set")

        clone = PolicySet(
            name=published.name,
            slug=f"{published.slug}-v{published.published_version + 1}",
            framework=published.framework,
            version=published.version,
            description=published.description,
            source_profile=published.source_profile,
            status="DRAFT",
            published_version=published.published_version + 1,
            parent_policy_set_id=published.id,
            is_enabled=False,
        )
        self.db.add(clone)
        await self.db.flush()

        rule_ids = (
            (await self.db.execute(select(PolicySetRule.rule_id).where(PolicySetRule.policy_set_id == published.id)))
            .scalars()
            .all()
        )
        for rule_id in rule_ids:
            self.db.add(PolicySetRule(policy_set_id=clone.id, rule_id=rule_id))
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.policy_set_new_version_created",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="policy_set",
            resource_id=str(clone.id),
            changes={"parent_policy_set_id": str(published.id), "published_version": clone.published_version},
        )
        return clone
