"""
LokiLinux — hand-curated CEL rule content loader (docs/compliance §3, §10, §43).

Loads backend/lokilinux/content/rules/*.yaml — the ~25-rule reference set
covering sshd/sysctl/sudo/firewall/selinux/mounts/users, each with a real
CEL check_expr against the agent collectors' actual fact shapes (verified
against agent/internal/compliance/*_collector.go directly, not guessed).
This is the honest complement to complianceascode_importer.py: that importer
can only ever set check_source=OVAL_UNMAPPED (mapping OVAL to a CEL
expression against this project's Facts schema is a hand-curated pass by
design, per that module's own docstring) — this loader is that hand-curated
pass for a deliberately small, high-confidence set of rules.

Idempotent on rule_key, but unlike ComplianceAsCodeImporter (which
preserves an existing row's check_source/check_expr across re-import so a
hand-curated mapping survives), this loader always overwrites — it *is*
the source of truth for these specific rule_keys, so a content fix in the
YAML must actually take effect on the next load.

Also idempotently ensures one PolicySet ("LokiLinux Curated Baseline")
containing every rule this loader manages, and one GLOBAL PolicyAssignment
for it — without an assignment, F2/F3's policy resolution finds nothing to
evaluate and these rules sit inert no matter how many exist in the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_rule import ComplianceRule, PolicyAssignment, PolicySet, PolicySetRule, RemediationTemplate
from lokilinux.services.framework_mapping import backfill_framework_mappings, preload_framework_cache

_CONTENT_DIR = Path(__file__).resolve().parent.parent / "content" / "rules"
_SOURCE = "lokilinux-curated"
_SOURCE_VERSION = "curated-2026.08"
_POLICY_SET_SLUG = "lokilinux-curated-baseline"


@dataclass
class LoadResult:
    rules_loaded: int = 0
    policy_set_created: bool = False
    assignment_created: bool = False


class CuratedRulesLoader:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def load_all(self, content_dir: Path | None = None) -> LoadResult:
        content_dir = content_dir or _CONTENT_DIR
        result = LoadResult()
        rule_ids: list[UUID] = []
        framework_cache = await preload_framework_cache(self.db)

        for yaml_path in sorted(content_dir.glob("*.yaml")):
            entries = yaml.safe_load(yaml_path.read_text()) or []
            for entry in entries:
                rule_id = await self._upsert_rule(entry)
                rule_ids.append(rule_id)
                await self._replace_resources(rule_id, entry)
                await self._upsert_remediation(rule_id, entry)
                await backfill_framework_mappings(
                    self.db, framework_cache, rule_id, entry.get("standard_refs") or {}, _SOURCE_VERSION
                )
                result.rules_loaded += 1

        policy_set_id, created = await self._ensure_policy_set(rule_ids)
        result.policy_set_created = created
        result.assignment_created = await self._ensure_global_assignment(policy_set_id)

        await self.db.commit()
        return result

    async def _upsert_rule(self, entry: dict) -> UUID:
        existing = (
            await self.db.execute(select(ComplianceRule).where(ComplianceRule.rule_key == entry["rule_key"]))
        ).scalar_one_or_none()

        fields = dict(
            title=entry["title"],
            description=entry.get("description"),
            rationale=entry.get("rationale"),
            severity=entry["severity"],
            domain=entry["domain"],
            check_source="CEL",
            check_expr=entry["check_expr"],
            expected_value=entry.get("expected_value"),
            platform_filter=entry.get("platform_filter") or [],
            standard_refs=entry.get("standard_refs") or {},
            source=_SOURCE,
            source_version=_SOURCE_VERSION,
            status="ACTIVE",
        )

        if existing is None:
            row = ComplianceRule(rule_key=entry["rule_key"], **fields)
            self.db.add(row)
            await self.db.flush()
            return row.id

        for key, value in fields.items():
            setattr(existing, key, value)
        await self.db.flush()
        return existing.id

    async def _replace_resources(self, rule_id: UUID, entry: dict) -> None:
        """Wholesale replace (docs/compliance §3 content is small and
        versioned as a whole) — a rule_resources row for every declared
        FILE resource plus every evidence_paths entry (resource_type
        FACT_PATH, the F2/F3 evidence-extraction + incremental-eval index)."""
        await self.db.execute(text("DELETE FROM compliance_rule_resources WHERE rule_id = :rule_id"), {"rule_id": rule_id})

        for res in entry.get("resources") or []:
            await self.db.execute(
                text(
                    "INSERT INTO compliance_rule_resources (rule_id, resource_type, resource_path) "
                    "VALUES (:rule_id, :type, :path) ON CONFLICT DO NOTHING"
                ),
                {"rule_id": rule_id, "type": res["type"], "path": res["path"]},
            )
        for path in entry.get("evidence_paths") or []:
            await self.db.execute(
                text(
                    "INSERT INTO compliance_rule_resources (rule_id, resource_type, resource_path) "
                    "VALUES (:rule_id, 'FACT_PATH', :path) ON CONFLICT DO NOTHING"
                ),
                {"rule_id": rule_id, "path": path},
            )

    async def _upsert_remediation(self, rule_id: UUID, entry: dict) -> None:
        remediation = entry.get("remediation")
        if not remediation:
            return

        template = (
            await self.db.execute(
                select(RemediationTemplate).where(
                    RemediationTemplate.rule_key == entry["rule_key"],
                    RemediationTemplate.provider == remediation["provider"],
                    RemediationTemplate.version == 1,
                )
            )
        ).scalar_one_or_none()

        if template is None:
            template = RemediationTemplate(
                rule_key=entry["rule_key"],
                provider=remediation["provider"],
                body=remediation["body"],
                rollback_body=remediation.get("rollback"),
                source=_SOURCE,
                version=1,
            )
            self.db.add(template)
            await self.db.flush()
        else:
            template.body = remediation["body"]
            template.rollback_body = remediation.get("rollback")
            await self.db.flush()

        rule = await self.db.get(ComplianceRule, rule_id)
        rule.remediation_template_id = template.id

    async def _ensure_policy_set(self, rule_ids: list[UUID]) -> tuple[UUID, bool]:
        policy_set = (
            await self.db.execute(select(PolicySet).where(PolicySet.slug == _POLICY_SET_SLUG))
        ).scalar_one_or_none()
        created = False
        if policy_set is None:
            policy_set = PolicySet(
                name="LokiLinux Curated Baseline",
                slug=_POLICY_SET_SLUG,
                framework="INTERNAL",
                version=_SOURCE_VERSION,
                description="Hand-curated CEL rules shipped with LokiLinux — sshd/sysctl/sudo/firewall/selinux/mounts/users.",
                source_profile=None,
                status="PUBLISHED",
                is_enabled=True,
            )
            self.db.add(policy_set)
            await self.db.flush()
            created = True
        else:
            policy_set.version = _SOURCE_VERSION

        existing_rule_ids = set(
            (
                await self.db.execute(
                    select(PolicySetRule.rule_id).where(PolicySetRule.policy_set_id == policy_set.id)
                )
            )
            .scalars()
            .all()
        )
        for rule_id in rule_ids:
            if rule_id not in existing_rule_ids:
                self.db.add(PolicySetRule(policy_set_id=policy_set.id, rule_id=rule_id))
        await self.db.flush()
        return policy_set.id, created

    async def _ensure_global_assignment(self, policy_set_id: UUID) -> bool:
        existing = (
            await self.db.execute(
                select(PolicyAssignment).where(
                    PolicyAssignment.policy_set_id == policy_set_id, PolicyAssignment.scope_type == "GLOBAL"
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        self.db.add(PolicyAssignment(policy_set_id=policy_set_id, scope_type="GLOBAL", scope_selector={}))
        await self.db.flush()
        return True
