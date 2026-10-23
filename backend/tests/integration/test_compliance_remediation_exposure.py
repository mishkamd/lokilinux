"""Integration tests for the remediation surface (MIS-225).

`remediation_templates` holds the command that fixes a rule and its
rollback. It was populated (21 rows for the curated content) but exposed
by nothing — the content existed in the DB and was invisible.

The command body is operator-grade detail: it is what would run on a host.
So the *existence* of a remediation is visible to every role, and the body
only to the roles that can act on a host.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.models.compliance_rule import ComplianceRule, RemediationTemplate


@pytest.fixture
def as_role(client):
    app = client._transport.app
    saved = app.dependency_overrides.get(get_current_user)

    def _set(role: str) -> dict:
        user = {"id": str(uuid.uuid4()), "role": role, "username": "t"}
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    yield _set
    if saved is None:
        app.dependency_overrides.pop(get_current_user, None)
    else:
        app.dependency_overrides[get_current_user] = saved


async def _rule_with_remediation(db_session: AsyncSession) -> ComplianceRule:
    rule = ComplianceRule(
        id=uuid.uuid4(),
        rule_key="SSH-001",
        title="Disable SSH root login",
        severity="CRITICAL",
        domain="sshd",
        check_source="CEL",
        standard_refs={"cis": "5.2.10"},
        source="lokilinux-curated",
        platform_filter=["rocky9"],
        is_enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()
    db_session.add(
        RemediationTemplate(
            rule_key="SSH-001",
            provider="shell",
            body="sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config",
            rollback_body="sed -i 's/^PermitRootLogin.*/#PermitRootLogin yes/' /etc/ssh/sshd_config",
            source="lokilinux-curated",
            version=1,
        )
    )
    await db_session.commit()
    return rule


@pytest.mark.asyncio
async def test_rule_detail_exposes_remediation_to_operators(
    client: AsyncClient, db_session: AsyncSession
):
    rule = await _rule_with_remediation(db_session)

    res = await client.get(f"/api/v1/compliance/rules/{rule.id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_remediation"] is True
    assert body["remediation"]["provider"] == "shell"
    assert "PermitRootLogin no" in body["remediation"]["body"]
    assert body["remediation"]["rollback_body"]


@pytest.mark.asyncio
async def test_rule_detail_hides_remediation_body_from_auditors(
    client: AsyncClient, db_session: AsyncSession, as_role
):
    rule = await _rule_with_remediation(db_session)
    as_role("AUDITOR")

    res = await client.get(f"/api/v1/compliance/rules/{rule.id}")
    assert res.status_code == 200, res.text
    body = res.json()
    # existence is visible...
    assert body["has_remediation"] is True
    # ...the command is not
    assert body["remediation"] is None


@pytest.mark.asyncio
async def test_rule_without_remediation_reports_none(
    client: AsyncClient, db_session: AsyncSession
):
    rule = ComplianceRule(
        id=uuid.uuid4(),
        rule_key="NO-REM-001",
        title="A rule with no remediation",
        severity="LOW",
        domain="users",
        check_source="CEL",
        source="complianceascode",
        platform_filter=[],
        is_enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    res = await client.get(f"/api/v1/compliance/rules/{rule.id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_remediation"] is False
    assert body["remediation"] is None


@pytest.mark.asyncio
async def test_policy_set_remediation_lists_every_rule(
    client: AsyncClient, db_session: AsyncSession
):
    rule = await _rule_with_remediation(db_session)
    other = ComplianceRule(
        id=uuid.uuid4(),
        rule_key="NO-REM-002",
        title="A rule with no remediation",
        severity="LOW",
        domain="users",
        check_source="CEL",
        source="complianceascode",
        platform_filter=[],
        is_enabled=True,
    )
    db_session.add(other)
    await db_session.commit()

    created = await client.post(
        "/api/v1/compliance/policy-sets",
        json={"name": "With remediation", "slug": "with-remediation", "framework": "INTERNAL"},
    )
    assert created.status_code == 201, created.text
    policy_set_id = created.json()["id"]
    for r in (rule, other):
        add = await client.post(
            f"/api/v1/compliance/policy-sets/{policy_set_id}/rules", json={"rule_id": str(r.id)}
        )
        assert add.status_code == 201, add.text

    res = await client.get(f"/api/v1/compliance/policy-sets/{policy_set_id}/remediation")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["policy_set_id"] == policy_set_id
    assert len(body["remediations"]) == 2
    by_key = {r["rule_key"]: r for r in body["remediations"]}
    assert by_key["SSH-001"]["remediation"]["provider"] == "shell"
    assert by_key["NO-REM-002"]["remediation"] is None


@pytest.mark.asyncio
async def test_policy_set_remediation_redacts_body_for_auditors(
    client: AsyncClient, db_session: AsyncSession, as_role
):
    rule = await _rule_with_remediation(db_session)
    created = await client.post(
        "/api/v1/compliance/policy-sets",
        json={"name": "Redacted", "slug": "redacted", "framework": "INTERNAL"},
    )
    policy_set_id = created.json()["id"]
    await client.post(
        f"/api/v1/compliance/policy-sets/{policy_set_id}/rules", json={"rule_id": str(rule.id)}
    )

    as_role("AUDITOR")
    res = await client.get(f"/api/v1/compliance/policy-sets/{policy_set_id}/remediation")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["remediations"][0]["remediation"] is None
    # the rule is still listed — a redacted row is not a missing row
    assert body["remediations"][0]["rule_key"] == "SSH-001"


@pytest.mark.asyncio
async def test_policy_set_remediation_404_for_unknown_set(client: AsyncClient):
    res = await client.get(f"/api/v1/compliance/policy-sets/{uuid.uuid4()}/remediation")
    assert res.status_code == 404


# ── MIS-231: the domain vocabulary ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_domains_endpoint_lists_the_canonical_vocabulary(
    client: AsyncClient, db_session: AsyncSession
):
    from lokilinux.compliance_domains import COMPLIANCE_DOMAINS

    rule = ComplianceRule(
        id=uuid.uuid4(),
        rule_key="D-001",
        title="A rule",
        severity="LOW",
        domain="sshd",
        check_source="CEL",
        source="complianceascode",
        platform_filter=[],
        is_enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    res = await client.get("/api/v1/compliance/domains")
    assert res.status_code == 200, res.text
    body = res.json()
    values = [d["value"] for d in body["domains"]]

    # every collector domain is offered — drift events come from collectors
    # that have no rule at all, and a filter that only offered the rule
    # domains would make those unreachable
    for domain in ("cron", "processes", "open_ports", "container_runtime"):
        assert domain in values
    assert "sshd" in values

    by_value = {d["value"]: d for d in body["domains"]}
    assert by_value["sshd"]["rules"] == 1
    assert by_value["sshd"]["category"] == "security"
    assert by_value["cron"]["rules"] == 0
    assert set(values) >= set(COMPLIANCE_DOMAINS)


@pytest.mark.asyncio
async def test_domains_endpoint_includes_a_domain_the_catalog_does_not_know(
    client: AsyncClient, db_session: AsyncSession
):
    """A rule for a domain outside the collector list (imported content) must
    still be filterable."""
    rule = ComplianceRule(
        id=uuid.uuid4(),
        rule_key="ODD-001",
        title="An odd domain",
        severity="LOW",
        domain="quantum",
        check_source="CEL",
        source="complianceascode",
        platform_filter=[],
        is_enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    res = await client.get("/api/v1/compliance/domains")
    assert res.status_code == 200
    by_value = {d["value"]: d for d in res.json()["domains"]}
    assert "quantum" in by_value
    assert by_value["quantum"]["rules"] == 1
