"""
LokiLinux — shared Framework/FrameworkVersion/Control/RuleMapping backfill
(docs/compliance §19), used by both the ComplianceAsCode importer
(services/complianceascode_importer.py) and the curated rule content loader
(services/curated_rules_loader.py) so the normalization logic exists once.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_framework import (
    ComplianceControl,
    ComplianceFramework,
    ComplianceFrameworkVersion,
    ComplianceRuleMapping,
)

# reference_N is complianceascode_importer's own positional fallback label
# for a <reference> with no href-derived key — never a real framework
# identifier. A standard_refs value that's itself a URL is excluded the
# same way — a framework Control needs a control identifier, not a link.
_SYNTHETIC_REF_KEY = re.compile(r"^reference_\d+$")


async def preload_framework_cache(db: AsyncSession) -> dict:
    """Bulk-loads every existing Framework/FrameworkVersion/Control row into
    in-memory dicts once, before a per-rule loop — never one get-or-create
    query per rule per standard_refs key (docs/compliance §38). New rows are
    added to these same dicts as they're created during the run, so a
    repeated key within one import also avoids a duplicate INSERT.
    """
    frameworks = (await db.execute(select(ComplianceFramework))).scalars().all()
    by_key = {f.key: f for f in frameworks}

    versions = (await db.execute(select(ComplianceFrameworkVersion))).scalars().all()
    by_fw_version = {(v.framework_id, v.version): v for v in versions}

    controls = (await db.execute(select(ComplianceControl))).scalars().all()
    by_version_control = {(c.framework_version_id, c.control_id): c for c in controls}

    # Bug fixed live (F9/F10 idempotency): without preloading existing
    # mappings too, a second run (this loader runs on every backend
    # startup) re-attempted every INSERT and hit
    # compliance_rule_mappings_pkey — the in-memory "mappings" set alone
    # only prevented a duplicate within a single run, never across runs.
    existing_mappings = (await db.execute(select(ComplianceRuleMapping))).scalars().all()
    mappings = {(m.rule_id, m.control_id) for m in existing_mappings}

    return {"frameworks": by_key, "versions": by_fw_version, "controls": by_version_control, "mappings": mappings}


async def backfill_framework_mappings(db: AsyncSession, cache: dict, rule_id, standard_refs: dict, content_version: str) -> None:
    """Normalizes standard_refs (the raw JSONB blob captured at import/load
    time) into queryable Framework -> FrameworkVersion -> Control ->
    RuleMapping rows — standard_refs itself stays untouched as the source
    of truth this is derived from."""
    for key, value in (standard_refs or {}).items():
        if _SYNTHETIC_REF_KEY.match(key) or not value or (isinstance(value, str) and value.startswith("http")):
            continue
        value = str(value)

        framework = cache["frameworks"].get(key)
        if framework is None:
            framework = ComplianceFramework(key=key, name=key.upper())
            db.add(framework)
            await db.flush()
            cache["frameworks"][key] = framework

        version = cache["versions"].get((framework.id, content_version))
        if version is None:
            version = ComplianceFrameworkVersion(framework_id=framework.id, version=content_version)
            db.add(version)
            await db.flush()
            cache["versions"][(framework.id, content_version)] = version

        control = cache["controls"].get((version.id, value))
        if control is None:
            control = ComplianceControl(framework_version_id=version.id, control_id=value, title=value)
            db.add(control)
            await db.flush()
            cache["controls"][(version.id, value)] = control

        mapping_key = (rule_id, control.id)
        if mapping_key not in cache["mappings"]:
            db.add(ComplianceRuleMapping(rule_id=rule_id, control_id=control.id))
            cache["mappings"].add(mapping_key)
