"""Integration tests for /api/v1/compliance/standards (Enterprise Compliance
plan U8/KTD6) — coverage math over compliance_frameworks/versions/controls/
rule_mappings + compliance_rules.check_source."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_framework import (
    ComplianceControl,
    ComplianceFramework,
    ComplianceFrameworkVersion,
    ComplianceRuleMapping,
)
from lokilinux.models.compliance_rule import ComplianceRule


def _rule(check_source: str) -> ComplianceRule:
    rid = uuid.uuid4()
    return ComplianceRule(
        id=rid,
        rule_key=f"rule-{rid}",
        title="A rule",
        severity="MEDIUM",
        domain="sshd" if check_source == "CEL" else "unmapped",
        check_source=check_source,
        is_enabled=check_source == "CEL",
    )


@pytest.mark.asyncio
async def test_list_standards_computes_executable_vs_reference_only(
    client: AsyncClient, db_session: AsyncSession
):
    framework = ComplianceFramework(key="cis-u8", name="CIS Benchmarks", publisher="CIS")
    db_session.add(framework)
    await db_session.commit()
    version = ComplianceFrameworkVersion(framework_id=framework.id, version="8.0")
    db_session.add(version)
    await db_session.commit()

    control = ComplianceControl(
        framework_version_id=version.id, control_id="5.2.10", title="SSH root login"
    )
    db_session.add(control)
    await db_session.commit()

    executable_rule = _rule("CEL")
    reference_rule_a = _rule("OVAL_UNMAPPED")
    reference_rule_b = _rule("OVAL_UNMAPPED")
    db_session.add_all([executable_rule, reference_rule_a, reference_rule_b])
    await db_session.commit()
    db_session.add_all(
        [
            ComplianceRuleMapping(rule_id=executable_rule.id, control_id=control.id),
            ComplianceRuleMapping(rule_id=reference_rule_a.id, control_id=control.id),
            ComplianceRuleMapping(rule_id=reference_rule_b.id, control_id=control.id),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/standards")
    assert resp.status_code == 200
    entry = next(s for s in resp.json() if s["key"] == "cis-u8")
    assert entry["version"] == "8.0"
    assert entry["publisher"] == "CIS"
    assert entry["rules_total"] == 3
    assert entry["executable"] == 1
    assert entry["reference_only"] == 2
    assert entry["coverage_executable_pct"] == round(100.0 / 3, 1)


@pytest.mark.asyncio
async def test_get_standard_detail_groups_rules_under_their_control(
    client: AsyncClient, db_session: AsyncSession
):
    framework = ComplianceFramework(key="nist-u8", name="NIST 800-53")
    db_session.add(framework)
    await db_session.commit()
    version = ComplianceFrameworkVersion(framework_id=framework.id, version="r5")
    db_session.add(version)
    await db_session.commit()
    control = ComplianceControl(
        framework_version_id=version.id, control_id="AC-6", title="Least Privilege"
    )
    db_session.add(control)
    await db_session.commit()
    rule = _rule("CEL")
    db_session.add(rule)
    await db_session.commit()
    db_session.add(ComplianceRuleMapping(rule_id=rule.id, control_id=control.id))
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/standards/nist-u8/r5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "NIST 800-53"
    assert len(body["controls"]) == 1
    assert body["controls"][0]["control_id"] == "AC-6"
    assert body["controls"][0]["rules"][0]["id"] == str(rule.id)
    assert body["controls"][0]["rules"][0]["check_source"] == "CEL"


@pytest.mark.asyncio
async def test_get_standard_404_for_unknown_key_or_version(
    client: AsyncClient, db_session: AsyncSession
):
    resp = await client.get("/api/v1/compliance/standards/does-not-exist/1.0")
    assert resp.status_code == 404

    framework = ComplianceFramework(key="only-v1", name="Only V1")
    db_session.add(framework)
    await db_session.commit()

    resp = await client.get("/api/v1/compliance/standards/only-v1/v2")
    assert resp.status_code == 404
