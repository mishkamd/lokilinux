"""Unit tests for the policy template resolver (pure selection logic, no DB).

A template is a *selection* over the rule catalog, not a copy of it —
services/policy_templates.py. These tests pin the selection semantics
(severity band, standard_ref key, source) that the whole "ready-made
profiles" feature rests on.
"""

from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.services.policy_templates import (
    PolicyTemplate,
    get_template,
    list_templates,
    severity_breakdown,
)


def _rule(
    key: str = "R-1",
    severity: str = "MEDIUM",
    domain: str = "sshd",
    standard_refs: dict | None = None,
    source: str = "complianceascode",
    check_source: str = "CEL",
) -> ComplianceRule:
    r = ComplianceRule()
    r.id = key  # type: ignore[assignment]
    r.rule_key = key
    r.title = f"Rule {key}"
    r.severity = severity
    r.domain = domain
    r.standard_refs = standard_refs or {}
    r.source = source
    r.check_source = check_source
    r.platform_filter = []
    r.is_enabled = True
    r.status = "ACTIVE"
    return r


def test_builtin_templates_have_unique_keys():
    keys = [t.key for t in list_templates()]
    assert len(keys) == len(set(keys))


def test_get_template_unknown_returns_none():
    assert get_template("does-not-exist") is None


def test_standard_ref_selects_only_rules_carrying_that_key():
    tpl = PolicyTemplate(key="t", name="T", description="", framework="CIS", standard_ref="cis")
    cis_rule = _rule("CIS-1", standard_refs={"cis": "5.2.10"})
    nist_rule = _rule("NIST-1", standard_refs={"nist": "AC-6"})
    assert tpl.matches(cis_rule)
    assert not tpl.matches(nist_rule)


def test_severity_band_is_inclusive_on_both_ends():
    tpl = PolicyTemplate(
        key="t",
        name="T",
        description="",
        framework="INTERNAL",
        min_severity="MEDIUM",
        max_severity="HIGH",
    )
    assert not tpl.matches(_rule("A", severity="LOW"))
    assert tpl.matches(_rule("B", severity="MEDIUM"))
    assert tpl.matches(_rule("C", severity="HIGH"))
    assert not tpl.matches(_rule("D", severity="CRITICAL"))


def test_min_severity_only_excludes_lower_severities():
    tpl = PolicyTemplate(
        key="t", name="T", description="", framework="INTERNAL", min_severity="HIGH"
    )
    assert not tpl.matches(_rule("A", severity="MEDIUM"))
    assert tpl.matches(_rule("B", severity="HIGH"))
    assert tpl.matches(_rule("C", severity="CRITICAL"))


def test_source_filter_selects_curated_rules_only():
    tpl = PolicyTemplate(
        key="t",
        name="T",
        description="",
        framework="INTERNAL",
        sources=("lokilinux-curated",),
    )
    assert tpl.matches(_rule("A", source="lokilinux-curated"))
    assert not tpl.matches(_rule("B", source="complianceascode"))


def test_unknown_severity_never_matches():
    tpl = PolicyTemplate(key="t", name="T", description="", framework="INTERNAL")
    assert not tpl.matches(_rule("A", severity="WHATEVER"))


def test_severity_override_is_per_template_not_per_rule():
    tpl = PolicyTemplate(
        key="t",
        name="T",
        description="",
        framework="INTERNAL",
        severity_overrides={"R-1": "CRITICAL"},
    )
    rule = _rule("R-1")
    assert tpl.severity_for(rule) == "CRITICAL"
    assert tpl.severity_for(_rule("R-2")) is None
    # the rule's own severity is untouched by the override
    assert rule.severity == "MEDIUM"


def test_severity_breakdown_counts_only_known_severities():
    counts = severity_breakdown(
        [_rule("A", severity="HIGH"), _rule("B", severity="HIGH"), _rule("C", severity="NOPE")]
    )
    assert counts["HIGH"] == 2
    assert counts["LOW"] == 0
