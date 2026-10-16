"""
LokiLinux — Compliance: Standards router (Enterprise Compliance plan U8/KTD6).

Read-only aggregation over compliance_frameworks -> versions -> controls ->
rule_mappings + compliance_rules.check_source — populated today by the
ComplianceAsCode importer and the curated rule loader (both go through
services/framework_mapping.py's backfill_framework_mappings), no new write
path. "executable" mirrors the exact definition already used by
get_policy_set_coverage (policy_engine.py): check_source == 'CEL'. Everything
else (OVAL_UNMAPPED/OSCAP_FALLBACK) is reference-only — never contributes to
scores or coverage, matching the Go evaluator's own early-return for
non-CEL rules.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.models.compliance_framework import (
    ComplianceControl,
    ComplianceFramework,
    ComplianceFrameworkVersion,
    ComplianceRuleMapping,
)
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.schemas.compliance_standards import (
    StandardControlResponse,
    StandardControlRuleResponse,
    StandardDetailResponse,
    StandardSummaryResponse,
)

router = APIRouter()


@router.get("/standards", response_model=list[StandardSummaryResponse])
async def list_standards(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[StandardSummaryResponse]:
    rows = (
        await db.execute(
            select(
                ComplianceFramework.key,
                ComplianceFramework.name,
                ComplianceFramework.publisher,
                ComplianceFramework.description,
                ComplianceFramework.status,
                ComplianceFrameworkVersion.version,
                func.count(func.distinct(ComplianceRuleMapping.rule_id)).label("rules_total"),
                func.count(func.distinct(ComplianceRuleMapping.rule_id))
                .filter(ComplianceRule.check_source == "CEL")
                .label("executable"),
            )
            .select_from(ComplianceFramework)
            .join(
                ComplianceFrameworkVersion,
                ComplianceFrameworkVersion.framework_id == ComplianceFramework.id,
            )
            .join(
                ComplianceControl,
                ComplianceControl.framework_version_id == ComplianceFrameworkVersion.id,
            )
            .join(ComplianceRuleMapping, ComplianceRuleMapping.control_id == ComplianceControl.id)
            .join(ComplianceRule, ComplianceRule.id == ComplianceRuleMapping.rule_id)
            .group_by(
                ComplianceFramework.key,
                ComplianceFramework.name,
                ComplianceFramework.publisher,
                ComplianceFramework.description,
                ComplianceFramework.status,
                ComplianceFrameworkVersion.version,
            )
            .order_by(ComplianceFramework.key, ComplianceFrameworkVersion.version)
        )
    ).all()

    return [
        StandardSummaryResponse(
            key=r.key,
            name=r.name,
            version=r.version,
            publisher=r.publisher,
            description=r.description,
            status=r.status,
            rules_total=r.rules_total,
            executable=r.executable,
            reference_only=r.rules_total - r.executable,
            coverage_executable_pct=(
                round(100.0 * r.executable / r.rules_total, 1) if r.rules_total else 0.0
            ),
        )
        for r in rows
    ]


@router.get("/standards/{key}/{version}", response_model=StandardDetailResponse)
async def get_standard(
    key: str,
    version: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> StandardDetailResponse:
    framework = (
        await db.execute(select(ComplianceFramework).where(ComplianceFramework.key == key))
    ).scalar_one_or_none()
    if framework is None:
        raise HTTPException(status_code=404, detail="Standard not found")
    fw_version = (
        await db.execute(
            select(ComplianceFrameworkVersion).where(
                ComplianceFrameworkVersion.framework_id == framework.id,
                ComplianceFrameworkVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if fw_version is None:
        raise HTTPException(status_code=404, detail="Standard version not found")

    rows = (
        await db.execute(
            select(ComplianceControl, ComplianceRule)
            .outerjoin(
                ComplianceRuleMapping, ComplianceRuleMapping.control_id == ComplianceControl.id
            )
            .outerjoin(ComplianceRule, ComplianceRule.id == ComplianceRuleMapping.rule_id)
            .where(ComplianceControl.framework_version_id == fw_version.id)
            .order_by(ComplianceControl.control_id)
        )
    ).all()

    controls: dict[str, StandardControlResponse] = {}
    for control, rule in rows:
        entry = controls.get(control.control_id)
        if entry is None:
            entry = StandardControlResponse(
                control_id=control.control_id,
                title=control.title,
                description=control.description,
                rules=[],
            )
            controls[control.control_id] = entry
        if rule is not None:
            entry.rules.append(
                StandardControlRuleResponse(
                    id=str(rule.id),
                    rule_key=rule.rule_key,
                    title=rule.title,
                    severity=rule.severity,
                    check_source=rule.check_source,
                    is_enabled=rule.is_enabled,
                )
            )

    return StandardDetailResponse(
        key=framework.key,
        name=framework.name,
        version=fw_version.version,
        publisher=framework.publisher,
        description=framework.description,
        status=framework.status,
        controls=list(controls.values()),
    )
