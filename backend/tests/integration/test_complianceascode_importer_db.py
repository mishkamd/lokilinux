"""Integration (DB-backed) tests for ComplianceAsCodeImporter's rule
persistence — Enterprise Compliance plan U8 Task 3 regression: imported
rules must land is_enabled=False (check_source=OVAL_UNMAPPED already keeps
them out of every evaluation, but is_enabled=True on an unexecutable rule
reads as a lie in the Rule Catalog UI) — and plan U3/KTD2: status must land
REFERENCE_ONLY, the field services/compliance's Go evaluator actually
filters on now."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.services.complianceascode_importer import ComplianceAsCodeImporter

DATASTREAM = b"""<?xml version="1.0" encoding="UTF-8"?>
<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2" id="xccdf_org.test_benchmark_u8">
  <title>U8 Test Benchmark</title>
  <Group id="xccdf_org.test_group_ssh">
    <Rule id="xccdf_org.test_rule_u8_sshd" severity="medium">
      <title>Disable SSH Root Login</title>
      <description>The root user should never log in directly.</description>
      <reference href="https://www.cisecurity.org">CIS 5.2.10</reference>
    </Rule>
  </Group>
</Benchmark>
"""


@pytest.mark.asyncio
async def test_import_creates_rule_disabled_and_unmapped(db_session: AsyncSession):
    result = await ComplianceAsCodeImporter(db_session).import_datastream(DATASTREAM, "1.0")
    assert result.rules_added == 1

    rule = (
        await db_session.execute(
            select(ComplianceRule).where(ComplianceRule.rule_key == "xccdf_org.test_rule_u8_sshd")
        )
    ).scalar_one()
    assert rule.check_source == "OVAL_UNMAPPED"
    assert rule.is_enabled is False
    assert rule.status == "REFERENCE_ONLY"


@pytest.mark.asyncio
async def test_reimport_does_not_re_disable_hand_curated_rule(db_session: AsyncSession):
    await ComplianceAsCodeImporter(db_session).import_datastream(DATASTREAM, "1.0")
    rule = (
        await db_session.execute(
            select(ComplianceRule).where(ComplianceRule.rule_key == "xccdf_org.test_rule_u8_sshd")
        )
    ).scalar_one()

    # Simulates an operator hand-curating a CEL check for this rule after
    # import — check_source/is_enabled/status all flip together, same as
    # curated_rules_loader.py does for its own managed rules.
    rule.check_source = "CEL"
    rule.check_expr = "facts.sshd.PermitRootLogin == 'no'"
    rule.is_enabled = True
    rule.status = "ACTIVE"
    await db_session.commit()

    result = await ComplianceAsCodeImporter(db_session).import_datastream(DATASTREAM, "1.1")
    assert result.rules_updated == 1

    rule_after = (
        await db_session.execute(
            select(ComplianceRule).where(ComplianceRule.rule_key == "xccdf_org.test_rule_u8_sshd")
        )
    ).scalar_one()
    assert rule_after.check_source == "CEL"
    assert rule_after.is_enabled is True
    # Reimport's existing-row branch never touches status — the same
    # non-clobbering guarantee it already gives check_source/is_enabled.
    assert rule_after.status == "ACTIVE"
