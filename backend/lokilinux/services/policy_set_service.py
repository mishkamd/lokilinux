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
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import safe_user_uuid
from lokilinux.models.compliance_rule import (
    ComplianceRule,
    PolicyAssignment,
    PolicySet,
    PolicySetRule,
)
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

    async def create_draft_with_rules(
        self,
        *,
        name: str,
        slug: str,
        framework: str,
        version: str | None,
        description: str | None,
        rules: list[tuple[UUID, str | None]],
        scope_type: str | None = None,
        scope_selector: dict[str, Any] | None = None,
        actor: dict[str, Any] | None = None,
    ) -> tuple[PolicySet, UUID | None]:
        """Creates a DRAFT policy set pre-populated with rules and, when a
        scope is given, its policy assignment — all in ONE transaction.

        This is the "create and apply" path: the alternative (create draft
        → POST rules N times → POST assignment → publish) is four round
        trips and leaves a half-built policy set behind if any step fails.
        A policy set that exists is a policy set that has its rules.

        rules is a list of (rule_id, severity_override) pairs.
        """
        existing = (
            await self.db.execute(select(PolicySet).where(PolicySet.slug == slug))
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Policy set slug '{slug}' already exists")

        policy_set = PolicySet(
            name=name, slug=slug, framework=framework, version=version, description=description,
            status="DRAFT", published_version=1, is_enabled=False,
        )
        self.db.add(policy_set)
        await self.db.flush()

        for rule_id, severity_override in rules:
            self.db.add(
                PolicySetRule(
                    policy_set_id=policy_set.id,
                    rule_id=rule_id,
                    severity_override=severity_override,
                )
            )

        assignment_id: UUID | None = None
        if scope_type:
            assignment = PolicyAssignment(
                policy_set_id=policy_set.id,
                scope_type=scope_type,
                scope_selector=scope_selector or {},
                is_enabled=True,
                created_by=safe_user_uuid(actor) if actor else None,
            )
            self.db.add(assignment)
            await self.db.flush()
            assignment_id = assignment.id

        await self.db.commit()
        await self.db.refresh(policy_set)

        await AuditService(self.db).log(
            action="compliance.policy_set_created",
            user_id=actor.get("id") if actor else None,
            actor_name=(actor.get("username") or actor.get("email")) if actor else None,
            resource_type="policy_set",
            resource_id=str(policy_set.id),
            changes={
                "name": name, "slug": slug, "framework": framework,
                "rules": len(rules), "scope_type": scope_type,
            },
        )
        return policy_set, assignment_id

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

    async def remove_rule(self, policy_set_id: UUID, rule_id: UUID, actor: dict) -> str:
        """Unlinks a rule from a DRAFT policy set. Returns the removed rule's
        key (for the audit trail).

        A PUBLISHED set is immutable by design — editing it means creating a
        new version (create_new_version), never mutating the rules under a
        version that is already live for the fleet.
        """
        policy_set = await self._get(policy_set_id)
        if policy_set.status != "DRAFT":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Policy set is {policy_set.status}; only a DRAFT can be edited. "
                    "Create a new version instead."
                ),
            )
        link = (
            await self.db.execute(
                select(PolicySetRule).where(
                    PolicySetRule.policy_set_id == policy_set_id,
                    PolicySetRule.rule_id == rule_id,
                )
            )
        ).scalar_one_or_none()
        if link is None:
            raise HTTPException(status_code=404, detail="Rule is not part of this policy set")
        rule_key = (
            await self.db.execute(
                select(ComplianceRule.rule_key).where(ComplianceRule.id == rule_id)
            )
        ).scalar_one_or_none()
        await self.db.delete(link)
        await self.db.commit()

        await AuditService(self.db).log(
            action="compliance.policy_set_rule_removed",
            user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("email"),
            resource_type="policy_set",
            resource_id=str(policy_set_id),
            changes={"rule_id": str(rule_id), "rule_key": rule_key},
        )
        return str(rule_key)

    async def export_profile(self, policy_set_id: UUID) -> dict:
        """The policy set as a portable profile: rule references by rule_key
        (stable across instances), not by UUID.

        This is the artifact that can be committed to git and reviewed — the
        point of the export is a diff a human reads, so it names rules the
        way a human knows them (SSH-001, CIS-5.2.10), not by surrogate key.
        """
        policy_set = await self._get(policy_set_id)
        rows = (
            await self.db.execute(
                select(
                    ComplianceRule.rule_key,
                    ComplianceRule.title,
                    PolicySetRule.severity_override,
                )
                .join(PolicySetRule, PolicySetRule.rule_id == ComplianceRule.id)
                .where(PolicySetRule.policy_set_id == policy_set_id)
                .order_by(ComplianceRule.rule_key)
            )
        ).all()
        return {
            "format": "lokilinux.policy-set/v1",
            "policy_set": {
                "name": policy_set.name,
                "slug": policy_set.slug,
                "framework": policy_set.framework,
                "version": policy_set.version,
                "description": policy_set.description,
                "source_profile": policy_set.source_profile,
                "remediation": policy_set.remediation,
            },
            "rules": [
                {"rule_key": rule_key, "title": title, "severity_override": override}
                for rule_key, title, override in rows
            ],
        }

    async def import_profile(
        self, profile: dict, slug: str | None, name: str | None, actor: dict
    ) -> tuple[PolicySet, list[str]]:
        """Creates a DRAFT policy set from an exported profile.

        Rules are matched by rule_key against the LOCAL catalog — a profile
        never carries rule bodies, so importing onto an instance that lacks
        the content imports what it can and reports the rest instead of
        silently creating a policy set with holes in it.
        """
        meta = profile.get("policy_set") or {}
        entries = profile.get("rules") or []
        wanted = [str(e.get("rule_key")) for e in entries if e.get("rule_key")]
        if not wanted:
            raise HTTPException(status_code=422, detail="Profile contains no rules")
        overrides = {
            str(e.get("rule_key")): e.get("severity_override")
            for e in entries
            if e.get("rule_key")
        }
        found = (
            await self.db.execute(select(ComplianceRule).where(ComplianceRule.rule_key.in_(wanted)))
        ).scalars().all()
        by_key = {r.rule_key: r for r in found}
        missing = [k for k in wanted if k not in by_key]

        target_slug = slug or str(meta.get("slug") or "")
        if not target_slug:
            raise HTTPException(status_code=422, detail="Profile has no slug; supply one")
        target_name = name or str(meta.get("name") or target_slug)

        policy_set, _ = await self.create_draft_with_rules(
            name=target_name,
            slug=target_slug,
            framework=str(meta.get("framework") or "INTERNAL"),
            version=meta.get("version"),
            description=meta.get("description"),
            rules=[(by_key[k].id, overrides.get(k)) for k in wanted if k in by_key],
            actor=actor,
        )
        return policy_set, missing
