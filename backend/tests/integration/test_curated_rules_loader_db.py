"""Integration (DB-backed) test for CuratedRulesLoader — Enterprise
Compliance plan U3/KTD2 regression: every rule this loader manages must
land status=ACTIVE on both insert and re-load (the loader always
overwrites its managed rows, docs at the top of curated_rules_loader.py),
since services/compliance's Go evaluator filters on this column now."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.services.curated_rules_loader import CuratedRulesLoader

_ENTRY_YAML = """
- rule_key: TEST-CURATED-001
  title: Test curated rule
  severity: LOW
  domain: test
  check_expr: 'facts.ok == true'
"""


@pytest.mark.asyncio
async def test_load_sets_status_active_on_insert_and_reload(db_session: AsyncSession, tmp_path):
    content_dir = tmp_path / "rules"
    content_dir.mkdir()
    (content_dir / "test.yaml").write_text(_ENTRY_YAML)

    loader = CuratedRulesLoader(db_session)
    result = await loader.load_all(content_dir)
    assert result.rules_loaded == 1

    rule = (
        await db_session.execute(
            select(ComplianceRule).where(ComplianceRule.rule_key == "TEST-CURATED-001")
        )
    ).scalar_one()
    assert rule.status == "ACTIVE"
    assert rule.check_source == "CEL"

    # Simulate drift (e.g. a stray admin edit) then re-load — the loader is
    # the source of truth for its managed rule_keys and must self-heal it.
    rule.status = "REFERENCE_ONLY"
    await db_session.commit()

    await CuratedRulesLoader(db_session).load_all(content_dir)
    rule_after = (
        await db_session.execute(
            select(ComplianceRule).where(ComplianceRule.rule_key == "TEST-CURATED-001")
        )
    ).scalar_one()
    assert rule_after.status == "ACTIVE"
