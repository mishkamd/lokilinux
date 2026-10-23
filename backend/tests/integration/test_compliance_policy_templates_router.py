"""Integration tests for the ready-made policy templates:
GET /api/v1/compliance/policy-templates,
GET /api/v1/compliance/rules/facets,
POST /api/v1/compliance/policy-sets/from-template.

The templates feature exists so an operator never has to hand-populate a
policy set rule by rule. These tests pin the three things that make that
safe: the counts shown before creating are the counts actually applied,
a template never picks up non-executable rules by default, and a creation
that matches nothing fails loudly instead of leaving an empty policy set.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_rule import (
    ComplianceRule,
    PolicyAssignment,
    PolicySet,
    PolicySetRule,
)


def _rule(
    key: str,
    severity: str = "MEDIUM",
    domain: str = "sshd",
    standard_refs: dict | None = None,
    source: str = "complianceascode",
    check_source: str = "CEL",
) -> ComplianceRule:
    rid = uuid.uuid4()
    return ComplianceRule(
        id=rid,
        rule_key=key,
        title=f"Rule {key}",
        severity=severity,
        domain=domain,
        check_source=check_source,
        standard_refs=standard_refs or {},
        source=source,
        platform_filter=["rocky9"],
        is_enabled=True,
    )


async def _seed(db_session: AsyncSession) -> list[ComplianceRule]:
    rules = [
        _rule("CIS-1", severity="HIGH", standard_refs={"cis": "5.2.10"}),
        _rule("CIS-2", severity="MEDIUM", standard_refs={"cis": "5.2.4"}),
        _rule("NIST-1", severity="LOW", standard_refs={"nist": "AC-6"}),
        _rule("CUR-1", severity="CRITICAL", source="lokilinux-curated"),
        _rule("UNMAPPED-1", severity="HIGH", check_source="OVAL_UNMAPPED"),
    ]
    db_session.add_all(rules)
    await db_session.commit()
    return rules


@pytest.mark.asyncio
async def test_list_policy_templates_returns_counts_from_live_catalog(
    client: AsyncClient, db_session: AsyncSession
):
    await _seed(db_session)

    res = await client.get("/api/v1/compliance/policy-templates")
    assert res.status_code == 200
    body = res.json()
    by_key = {t["key"]: t for t in body}

    assert "loki-linux-curated" in by_key
    assert by_key["loki-linux-curated"]["rule_count"] == 1
    assert by_key["loki-linux-curated"]["severity_breakdown"]["CRITICAL"] == 1

    # CIS template matches the two cis-mapped rules; NIST-mapped and
    # curated rules are not CIS rules.
    assert by_key["cis"]["rule_count"] == 2
    assert by_key["nist"]["rule_count"] == 1

    # non-executable rules are excluded by default
    assert by_key["essential"]["rule_count"] == 3  # CIS-1, CIS-2, CUR-1


@pytest.mark.asyncio
async def test_create_policy_set_from_template_populates_rules(
    client: AsyncClient, db_session: AsyncSession
):
    await _seed(db_session)

    res = await client.post(
        "/api/v1/compliance/policy-sets/from-template",
        json={"template_key": "cis"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["template_key"] == "cis"
    assert body["rules_added"] == 2
    assert body["severity_breakdown"]["HIGH"] == 1
    assert body["severity_breakdown"]["MEDIUM"] == 1
    assert body["assignment_id"] is None

    policy_set = (
        await db_session.execute(
            select(PolicySet).where(PolicySet.id == uuid.UUID(body["policy_set"]["id"]))
        )
    ).scalar_one()
    assert policy_set.status == "DRAFT"
    assert policy_set.is_enabled is False
    assert policy_set.framework == "CIS"

    linked = (
        (
            await db_session.execute(
                select(PolicySetRule).where(PolicySetRule.policy_set_id == policy_set.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(linked) == 2


@pytest.mark.asyncio
async def test_create_from_template_can_also_assign_a_scope(
    client: AsyncClient, db_session: AsyncSession
):
    await _seed(db_session)

    res = await client.post(
        "/api/v1/compliance/policy-sets/from-template",
        json={
            "template_key": "loki-linux-curated",
            "scope_type": "GLOBAL",
            "scope_selector": {},
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["assignment_id"] is not None

    assignment = (
        await db_session.execute(
            select(PolicyAssignment).where(PolicyAssignment.id == uuid.UUID(body["assignment_id"]))
        )
    ).scalar_one()
    assert assignment.scope_type == "GLOBAL"
    assert assignment.policy_set_id == uuid.UUID(body["policy_set"]["id"])


@pytest.mark.asyncio
async def test_create_from_template_keeps_severity_override_local_to_the_set(
    client: AsyncClient, db_session: AsyncSession
):
    rules = await _seed(db_session)

    res = await client.post(
        "/api/v1/compliance/policy-sets/from-template",
        json={"template_key": "cis", "severity_overrides": {"CIS-1": "LOW"}},
    )
    assert res.status_code == 201, res.text
    policy_set_id = uuid.UUID(res.json()["policy_set"]["id"])

    linked = (
        (
            await db_session.execute(
                select(PolicySetRule).where(PolicySetRule.policy_set_id == policy_set_id)
            )
        )
        .scalars()
        .all()
    )
    overrides = {link.rule_id: link.severity_override for link in linked}
    cis1 = next(r for r in rules if r.rule_key == "CIS-1")
    assert overrides[cis1.id] == "LOW"
    # the catalog rule's own severity is untouched
    assert cis1.severity == "HIGH"


@pytest.mark.asyncio
async def test_create_from_template_fails_when_nothing_matches(
    client: AsyncClient, db_session: AsyncSession
):
    # no rules at all -> every template matches nothing
    res = await client.post(
        "/api/v1/compliance/policy-sets/from-template",
        json={"template_key": "cis"},
    )
    assert res.status_code == 409
    assert "matches no rules" in res.json()["detail"]

    # and no half-built policy set was left behind
    count = (await db_session.execute(select(PolicySet))).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_create_from_template_rejects_unknown_template(
    client: AsyncClient, db_session: AsyncSession
):
    res = await client.post(
        "/api/v1/compliance/policy-sets/from-template",
        json={"template_key": "nope"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_rule_facets_report_real_values_with_counts(
    client: AsyncClient, db_session: AsyncSession
):
    await _seed(db_session)

    res = await client.get("/api/v1/compliance/rules/facets")
    assert res.status_code == 200
    body = res.json()

    domains = {d["value"]: d["count"] for d in body["domains"]}
    assert domains["sshd"] == 5

    platforms = {p["value"]: p["count"] for p in body["platforms"]}
    assert platforms["rocky9"] == 5

    frameworks = {f["value"]: f["count"] for f in body["frameworks"]}
    assert frameworks["cis"] == 2
    assert frameworks["nist"] == 1

    severities = {s["value"]: s["count"] for s in body["severities"]}
    assert severities["HIGH"] == 2


# ── MIS-228: rule removal + export/import round-trip ─────────────────────────


@pytest.mark.asyncio
async def test_remove_rule_from_draft(client: AsyncClient, db_session: AsyncSession):
    rules = await _seed(db_session)
    created = await client.post(
        "/api/v1/compliance/policy-sets/from-template", json={"template_key": "cis"}
    )
    policy_set_id = uuid.UUID(created.json()["policy_set"]["id"])

    res = await client.delete(f"/api/v1/compliance/policy-sets/{policy_set_id}/rules/{rules[0].id}")
    assert res.status_code == 204, res.text

    linked = (
        await db_session.execute(
            select(PolicySetRule).where(PolicySetRule.policy_set_id == policy_set_id)
        )
    ).scalars().all()
    assert len(linked) == 1


@pytest.mark.asyncio
async def test_remove_rule_rejected_on_published_set(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)
    created = await client.post(
        "/api/v1/compliance/policy-sets/from-template", json={"template_key": "cis"}
    )
    policy_set_id = uuid.UUID(created.json()["policy_set"]["id"])
    publish = await client.post(f"/api/v1/compliance/policy-sets/{policy_set_id}/publish")
    assert publish.status_code == 200, publish.text

    res = await client.delete(f"/api/v1/compliance/policy-sets/{policy_set_id}/rules/{uuid.uuid4()}")
    assert res.status_code == 409
    assert "only a DRAFT" in res.json()["detail"]


@pytest.mark.asyncio
async def test_remove_rule_404_when_not_in_set(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)
    created = await client.post(
        "/api/v1/compliance/policy-sets/from-template", json={"template_key": "cis"}
    )
    policy_set_id = uuid.UUID(created.json()["policy_set"]["id"])

    res = await client.delete(f"/api/v1/compliance/policy-sets/{policy_set_id}/rules/{uuid.uuid4()}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_export_then_import_round_trip(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)
    created = await client.post(
        "/api/v1/compliance/policy-sets/from-template",
        json={"template_key": "cis", "severity_overrides": {"CIS-1": "LOW"}},
    )
    policy_set_id = created.json()["policy_set"]["id"]

    export = await client.get(f"/api/v1/compliance/policy-sets/{policy_set_id}/export")
    assert export.status_code == 200, export.text
    profile = export.json()
    assert profile["format"] == "lokilinux.policy-set/v1"
    assert {r["rule_key"] for r in profile["rules"]} == {"CIS-1", "CIS-2"}
    overrides = {r["rule_key"]: r["severity_override"] for r in profile["rules"]}
    assert overrides["CIS-1"] == "LOW"

    # Re-import the exported profile under a new slug → same rules, same override.
    imported = await client.post(
        "/api/v1/compliance/policy-sets/import-profile",
        json={"profile": profile, "slug": "cis-round-trip", "name": "CIS round trip"},
    )
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["rules_imported"] == 2
    assert body["missing_rules"] == []
    assert body["policy_set"]["status"] == "DRAFT"

    new_id = uuid.UUID(body["policy_set"]["id"])
    linked = (
        await db_session.execute(
            select(PolicySetRule).where(PolicySetRule.policy_set_id == new_id)
        )
    ).scalars().all()
    assert len(linked) == 2
    assert {link.severity_override for link in linked} == {"LOW", None}


@pytest.mark.asyncio
async def test_export_yaml(client: AsyncClient, db_session: AsyncSession):
    await _seed(db_session)
    created = await client.post(
        "/api/v1/compliance/policy-sets/from-template", json={"template_key": "cis"}
    )
    policy_set_id = created.json()["policy_set"]["id"]

    res = await client.get(f"/api/v1/compliance/policy-sets/{policy_set_id}/export?format=yaml")
    assert res.status_code == 200
    assert "application/yaml" in res.headers["content-type"]
    assert "CIS-1" in res.text


@pytest.mark.asyncio
async def test_import_profile_reports_missing_rules(client: AsyncClient, db_session: AsyncSession):
    # a rule_key the local catalog does not know
    profile = {
        "format": "lokilinux.policy-set/v1",
        "policy_set": {"name": "From elsewhere", "slug": "from-elsewhere", "framework": "CIS"},
        "rules": [{"rule_key": "CIS-1"}, {"rule_key": "SSH-999"}],
    }
    rules = await _seed(db_session)

    res = await client.post(
        "/api/v1/compliance/policy-sets/import-profile", json={"profile": profile}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["rules_imported"] == 1
    assert body["missing_rules"] == ["SSH-999"]
    assert rules[0].rule_key == "CIS-1"
