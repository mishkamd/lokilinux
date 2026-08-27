"""
LokiLinux — ComplianceAsCode content importer (docs/compliance/07-POLICY-ENGINE.md).

Parses a standard XCCDF 1.2 datastream (the format `scap-security-guide` /
`openscap` ship and `oscap xccdf eval` consumes) rather than the upstream
ComplianceAsCode/content git repo's raw `rule.yml` sources directly —
verified against a real rule.yml fetched from the upstream repo, those
files embed unresolved Jinja macro calls (`{{{ complete_ocil_entry_...() }}}`)
at the top level, which is not valid standalone YAML; producing it requires
running ComplianceAsCode's full Python/CMake build pipeline
(build-scripts/compile_product.py and friends), which is far beyond an
"importer" and isn't something this service should embed. The *build
output* of that pipeline — an XCCDF 1.2 datastream — is the real, stable,
standards-based (NIST IR 7275) integration point: it's what `oscap` itself
consumes, it's what distro `scap-security-guide` packages ship at
`/usr/share/xml/scap/ssg/content/*.xml`, and it's schema-verified against a
real fixture (openscap/tests/API/XCCDF/parser/xccdf12.xml) rather than
guessed.

check_source is always set to OVAL_UNMAPPED on import, never CEL — per D4,
mapping a rule's OVAL-oriented check to a CEL expression against this
module's Facts schema is a hand-curated pass, deliberately not attempted
here. domain is set to "unmapped" for the same reason: generic XCCDF has no
concept of this module's collector domains (sshd/sysctl/...), so guessing
one from a rule's title/id would be false precision. Both are honest gaps,
matching the "coverage is real, never silently 100%" design already in
compliance_rules.check_source.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse
from xml.etree import ElementTree

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_rule import ComplianceRule, PolicySet, PolicySetRule
from lokilinux.services.framework_mapping import backfill_framework_mappings, preload_framework_cache

XCCDF_NS = "http://checklists.nist.gov/xccdf/1.2"

_FRAMEWORK_HINTS = ["cis", "stig", "pci", "nist", "iso27001"]


def _qname(tag: str) -> str:
    return f"{{{XCCDF_NS}}}{tag}"


def _text(elem: ElementTree.Element | None) -> str | None:
    """Extracts all text content of an element, including text inside
    nested inline markup (e.g. XCCDF's xhtml-namespaced description
    bodies) — itertext() walks the whole subtree rather than just
    elem.text, which would silently drop anything after the first child.
    """
    if elem is None:
        return None
    text = "".join(elem.itertext()).strip()
    return text or None


_SEVERITY_MAP = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"}


def _normalize_severity(raw: str | None) -> str:
    return _SEVERITY_MAP.get((raw or "").lower(), "MEDIUM")


@dataclass
class RuleData:
    rule_key: str
    title: str
    description: str | None
    rationale: str | None
    severity: str
    standard_refs: dict = field(default_factory=dict)


@dataclass
class ProfileData:
    profile_id: str
    title: str
    framework: str
    rule_keys: list[str] = field(default_factory=list)


def _find_benchmark(root: ElementTree.Element) -> ElementTree.Element:
    """A datastream wraps Benchmark inside ds:component; a bare Benchmark
    export doesn't. Searching the whole tree for the first Benchmark
    element handles both without hand-parsing the datastream envelope.
    """
    if root.tag == _qname("Benchmark"):
        return root
    found = root.find(f".//{_qname('Benchmark')}")
    if found is None:
        raise ValueError("no XCCDF Benchmark element found in document")
    return found


def parse_xccdf_rules(xml_bytes: bytes) -> list[RuleData]:
    root = ElementTree.fromstring(xml_bytes)
    benchmark = _find_benchmark(root)

    rules = []
    for rule_elem in benchmark.iter(_qname("Rule")):
        rule_key = rule_elem.get("id")
        if not rule_key:
            continue  # malformed entry — no stable key to import against

        standard_refs: dict[str, str] = {}
        for ident in rule_elem.findall(_qname("ident")):
            system = ident.get("system") or "ident"
            # "http://cce.mitre.org" -> "cce" (first label of the hostname) —
            # short, stable key.
            hostname = urlparse(system).netloc or system
            key = hostname.split(".")[0] or system
            if ident.text:
                standard_refs[key] = ident.text.strip()
        for i, ref in enumerate(rule_elem.findall(_qname("reference"))):
            label = ref.get("href") or f"reference_{i}"
            if ref.text:
                standard_refs[label] = ref.text.strip()

        rules.append(
            RuleData(
                rule_key=rule_key,
                title=_text(rule_elem.find(_qname("title"))) or rule_key,
                description=_text(rule_elem.find(_qname("description"))),
                rationale=_text(rule_elem.find(_qname("rationale"))),
                severity=_normalize_severity(rule_elem.get("severity")),
                standard_refs=standard_refs,
            )
        )
    return rules


def parse_xccdf_profiles(xml_bytes: bytes) -> list[ProfileData]:
    root = ElementTree.fromstring(xml_bytes)
    benchmark = _find_benchmark(root)

    profiles = []
    for profile_elem in benchmark.findall(_qname("Profile")):
        profile_id = profile_elem.get("id")
        if not profile_id:
            continue

        rule_keys: list[str] = []
        for sel in profile_elem.findall(_qname("select")):
            idref = sel.get("idref")
            if sel.get("selected") == "true" and idref:
                rule_keys.append(idref)

        title = _text(profile_elem.find(_qname("title"))) or profile_id
        haystack = f"{profile_id} {title}".lower()
        framework = next(
            (
                hint.upper().replace("ISO27001", "ISO27001")
                for hint in _FRAMEWORK_HINTS
                if re.search(hint, haystack)
            ),
            "INTERNAL",
        )

        profiles.append(
            ProfileData(
                profile_id=profile_id, title=title, framework=framework, rule_keys=rule_keys
            )
        )
    return profiles


@dataclass
class ImportResult:
    rules_imported: int = 0
    rules_updated: int = 0
    policy_sets_imported: int = 0
    # Diff summary (docs/compliance §41) — added/modified/removed/unchanged
    # against whatever complianceascode-sourced rules existed before this
    # run. rules_removed is a count only: matching §41's "never
    # automatically destroy old rule versions," nothing is deleted or
    # disabled, the rule row simply wasn't present in the new datastream.
    rules_added: int = 0
    rules_modified: int = 0
    rules_unchanged: int = 0
    rules_removed: int = 0


def _rule_content_hash(title: str, description: str | None, rationale: str | None, severity: str, standard_refs: dict) -> str:
    """Stable fingerprint of the fields import_datastream can change on an
    existing row — used to tell "re-imported identical" (unchanged) apart
    from "content actually changed" (modified) for the diff summary."""
    import json

    body = json.dumps(
        {"title": title, "description": description, "rationale": rationale, "severity": severity, "standard_refs": standard_refs},
        sort_keys=True,
    )
    return hashlib.sha256(body.encode()).hexdigest()


class ComplianceAsCodeImporter:
    """Idempotent on rule_key: re-importing the same or a newer datastream
    upserts compliance_rules content fields but never touches check_source/
    check_expr on an existing row — a hand-curated CEL mapping must survive
    a re-import untouched.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def import_datastream(
        self,
        xml_bytes: bytes,
        content_version: str,
        selected_profile_ids: list[str] | None = None,
    ) -> ImportResult:
        rules = parse_xccdf_rules(xml_bytes)
        profiles = parse_xccdf_profiles(xml_bytes)
        if selected_profile_ids:
            profiles = [p for p in profiles if p.profile_id in selected_profile_ids]

        result = ImportResult()
        rule_key_to_id = {}

        # Diff baseline: every rule_key this source previously imported,
        # before this run touches anything (docs/compliance §41).
        previously_imported_keys = set(
            (
                await self.db.execute(
                    select(ComplianceRule.rule_key).where(ComplianceRule.source == "complianceascode")
                )
            )
            .scalars()
            .all()
        )
        new_keys = {r.rule_key for r in rules}
        result.rules_removed = len(previously_imported_keys - new_keys)

        framework_cache = await preload_framework_cache(self.db)

        for r in rules:
            existing = (
                await self.db.execute(
                    select(ComplianceRule).where(ComplianceRule.rule_key == r.rule_key)
                )
            ).scalar_one_or_none()
            content_hash = _rule_content_hash(r.title, r.description, r.rationale, r.severity, r.standard_refs)

            if existing is None:
                row = ComplianceRule(
                    rule_key=r.rule_key,
                    title=r.title,
                    description=r.description,
                    rationale=r.rationale,
                    severity=r.severity,
                    domain="unmapped",
                    check_source="OVAL_UNMAPPED",
                    standard_refs=r.standard_refs,
                    source="complianceascode",
                    source_version=content_version,
                    # is_enabled defaults True on the model — force it off
                    # here (plan U8 Task 3): check_source already keeps
                    # this rule out of every evaluation/score regardless,
                    # but is_enabled=True on an unexecutable rule reads as
                    # a lie in the Rule Catalog UI. Only at creation, same
                    # as check_source above — a later hand-curated CEL
                    # mapping (which does update is_enabled) must survive
                    # untouched here.
                    is_enabled=False,
                )
                self.db.add(row)
                await self.db.flush()
                rule_key_to_id[r.rule_key] = row.id
                result.rules_imported += 1
                result.rules_added += 1
            else:
                existing_hash = _rule_content_hash(
                    existing.title, existing.description, existing.rationale, existing.severity, existing.standard_refs
                )
                existing.title = r.title
                existing.description = r.description
                existing.rationale = r.rationale
                existing.severity = r.severity
                existing.standard_refs = r.standard_refs
                existing.source_version = content_version
                rule_key_to_id[r.rule_key] = existing.id
                result.rules_updated += 1
                if existing_hash == content_hash:
                    result.rules_unchanged += 1
                else:
                    result.rules_modified += 1

            await backfill_framework_mappings(
                self.db, framework_cache, rule_key_to_id[r.rule_key], r.standard_refs, content_version
            )

        for p in profiles:
            policy_set = (
                await self.db.execute(select(PolicySet).where(PolicySet.slug == p.profile_id))
            ).scalar_one_or_none()

            if policy_set is None:
                policy_set = PolicySet(
                    name=p.title,
                    slug=p.profile_id,
                    framework=p.framework,
                    version=content_version,
                    source_profile=p.profile_id,
                )
                self.db.add(policy_set)
                await self.db.flush()
            else:
                policy_set.version = content_version

            # Replace membership wholesale — "this policy set now reflects
            # the imported profile's rule list" is simpler and more
            # predictable than diffing add/remove.
            await self.db.execute(
                delete(PolicySetRule).where(PolicySetRule.policy_set_id == policy_set.id)
            )
            for rule_key in p.rule_keys:
                rule_id = rule_key_to_id.get(rule_key)
                if rule_id is None:
                    continue  # profile selects a rule not in this datastream — skip, don't fail
                self.db.add(PolicySetRule(policy_set_id=policy_set.id, rule_id=rule_id))
            result.policy_sets_imported += 1

        await self.db.commit()
        return result
