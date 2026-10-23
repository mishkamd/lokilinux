"""
LokiLinux — Policy templates: named rule selections over the rule catalog.

One rule body, many named profiles. This is the pattern every enterprise
tool converged on: ComplianceAsCode ships one XCCDF body and many named
profiles (cis_level1_server, cis_level2_server, stig profiles), CIS ships
Benchmarks with Level 1/Level 2 selections, Wazuh ships "CIS Distribution"
policy files, Tenable ships baselines that select plugins. Nobody ships
a second copy of the same check for every profile — the profile is a
*selection*, and the check body is shared.

A template here is exactly that: a selector (framework reference + severity
band + source) resolved against `compliance_rules` at creation time. The
same catalog backs every template, so a rule fix propagates everywhere and
the policy set is never a stale copy of the rules.

Two honest limits, both surfaced in the API rather than hidden:

1. A template is a selection over the rules *imported into this catalog*,
   not an official certified benchmark. "CIS" here means "every rule in the
   catalog whose standard_refs carry a `cis` key" — it is not CIS's
   copyrighted Benchmark text and does not claim to be.
2. Non-executable rules (check_source != CEL) are excluded by default.
   They carry no expression the Go evaluator can run, so including them
   would inflate the rule count while producing no verdicts. Callers can
   opt in with include_unmapped=True when they want reference coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_rule import ComplianceRule

# Severity order used for band filtering. Higher == more severe.
SEVERITY_ORDER: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _severity_rank(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index(severity.upper())
    except ValueError:
        return -1


@dataclass(frozen=True)
class PolicyTemplate:
    """A named selection over the rule catalog.

    standard_ref: key looked up in the rule's `standard_refs` JSONB
    (e.g. "cis", "nist", "stig", "pci-dss") — the rule counts as a match
    when that key is present, regardless of the reference value.
    sources: matches the rule's `source` column (e.g. "lokilinux-curated").
    min_severity / max_severity: inclusive band over SEVERITY_ORDER.
    """

    key: str
    name: str
    description: str
    framework: str
    standard_ref: str | None = None
    sources: tuple[str, ...] = ()
    min_severity: str | None = None
    max_severity: str | None = None
    severity_overrides: dict[str, str] = field(default_factory=dict)

    def matches(self, rule: ComplianceRule) -> bool:
        if self.standard_ref is not None and self.standard_ref not in (rule.standard_refs or {}):
            return False
        if self.sources and rule.source not in self.sources:
            return False
        rank = _severity_rank(rule.severity)
        if rank < 0:
            return False
        if self.min_severity is not None and rank < _severity_rank(self.min_severity):
            return False
        if self.max_severity is not None and rank > _severity_rank(self.max_severity):
            return False
        return True

    def severity_for(self, rule: ComplianceRule) -> str | None:
        """Per-profile severity override, if this template sets one."""
        return self.severity_overrides.get(rule.rule_key)


# The built-in templates. Kept small and honest: a framework selection, a
# severity band, and the hand-verified curated set. Everything else is a
# composition the user builds in the UI from a template + rule additions.
BUILTIN_TEMPLATES: tuple[PolicyTemplate, ...] = (
    PolicyTemplate(
        key="loki-linux-curated",
        name="LokiLinux Curated Baseline",
        description=(
            "The hand-curated, hand-verified rule set shipped with LokiLinux. "
            "Every rule here has a real CEL expression checked against the "
            "agent collectors' actual fact shapes. Start here."
        ),
        framework="INTERNAL",
        sources=("lokilinux-curated",),
    ),
    PolicyTemplate(
        key="essential",
        name="Essential hardening",
        description=(
            "Every medium-and-higher severity rule in the catalog, regardless "
            "of framework. A good default for fleets that cannot chase the "
            "long tail of low-severity hardening advice."
        ),
        framework="INTERNAL",
        min_severity="MEDIUM",
    ),
    PolicyTemplate(
        key="strict",
        name="Strict hardening",
        description=(
            "Only high and critical severity rules. The smallest useful "
            "profile — for fleets that want signal, not volume."
        ),
        framework="INTERNAL",
        min_severity="HIGH",
    ),
    PolicyTemplate(
        key="cis",
        name="CIS-mapped rules",
        description=(
            "Every rule in the catalog carrying a CIS reference. This is a "
            "selection over the local catalog, not CIS's certified Benchmark "
            "text — import ComplianceAsCode content for the official mapping."
        ),
        framework="CIS",
        standard_ref="cis",
    ),
    PolicyTemplate(
        key="nist",
        name="NIST-mapped rules",
        description="Every rule in the catalog carrying a NIST 800-53 control reference.",
        framework="NIST",
        standard_ref="nist",
    ),
    PolicyTemplate(
        key="stig",
        name="STIG-mapped rules",
        description="Every rule in the catalog carrying a DISA STIG control reference.",
        framework="STIG",
        standard_ref="stig",
    ),
    PolicyTemplate(
        key="pci-dss",
        name="PCI-DSS-mapped rules",
        description="Every rule in the catalog carrying a PCI-DSS requirement reference.",
        framework="PCI_DSS",
        standard_ref="pci-dss",
    ),
)

_TEMPLATES_BY_KEY: dict[str, PolicyTemplate] = {t.key: t for t in BUILTIN_TEMPLATES}


def list_templates() -> tuple[PolicyTemplate, ...]:
    return BUILTIN_TEMPLATES


def get_template(key: str) -> PolicyTemplate | None:
    return _TEMPLATES_BY_KEY.get(key)


def _candidate_query(include_unmapped: bool) -> Select[tuple[ComplianceRule]]:
    q = select(ComplianceRule).where(ComplianceRule.status != "DEPRECATED")
    if not include_unmapped:
        q = q.where(ComplianceRule.check_source == "CEL")
    return q


async def resolve_template_rules(
    db: AsyncSession,
    template: PolicyTemplate,
    *,
    include_unmapped: bool = False,
) -> list[ComplianceRule]:
    """Rules the template selects, in a stable order (severity desc, key)."""
    rows = (await db.execute(_candidate_query(include_unmapped))).scalars().all()
    matched = [r for r in rows if template.matches(r)]
    matched.sort(key=lambda r: (-_severity_rank(r.severity), r.rule_key))
    return matched


def severity_breakdown(rules: Iterable[ComplianceRule]) -> dict[str, int]:
    counts = {s: 0 for s in SEVERITY_ORDER}
    for rule in rules:
        if rule.severity in counts:
            counts[rule.severity] += 1
    return counts
