"""Unit tests for the ComplianceAsCode XCCDF parser (pure, no DB) —
docs/compliance/07-POLICY-ENGINE.md §1.

Fixture XML shape verified against a real XCCDF 1.2 file
(openscap/openscap tests/API/XCCDF/parser/xccdf12.xml) rather than guessed.
"""

from lokilinux.services.complianceascode_importer import (
    _normalize_severity,
    parse_xccdf_profiles,
    parse_xccdf_rules,
)

BARE_BENCHMARK = b"""<?xml version="1.0" encoding="UTF-8"?>
<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2" id="xccdf_org.test_benchmark_demo">
  <title>Demo Benchmark</title>
  <Profile id="xccdf_org.test_profile_cis_demo">
    <title>CIS Demo Profile</title>
    <select idref="xccdf_org.test_rule_sshd_disable_root_login" selected="true"/>
    <select idref="xccdf_org.test_rule_not_in_datastream" selected="true"/>
    <select idref="xccdf_org.test_rule_unselected" selected="false"/>
  </Profile>
  <Group id="xccdf_org.test_group_ssh">
    <Rule id="xccdf_org.test_rule_sshd_disable_root_login" severity="medium">
      <title>Disable SSH Root Login</title>
      <description>The root user should never log in directly.</description>
      <rationale>Individual accountability requires named-user login.</rationale>
      <ident system="http://cce.mitre.org">CCE-80901-2</ident>
      <reference href="https://www.cisecurity.org">CIS 5.2.10</reference>
    </Rule>
  </Group>
</Benchmark>
"""

DATASTREAM_WRAPPED = b"""<?xml version="1.0" encoding="UTF-8"?>
<ds:data-stream-collection xmlns:ds="urn:xccdf:datastream:1.2"
                            xmlns="http://checklists.nist.gov/xccdf/1.2"
                            id="scap_org.test_collection">
  <ds:component id="comp-1">
    <Benchmark id="xccdf_org.test_benchmark_wrapped">
      <title>Wrapped Benchmark</title>
      <Rule id="xccdf_org.test_rule_wrapped" severity="high">
        <title>Wrapped Rule</title>
      </Rule>
    </Benchmark>
  </ds:component>
</ds:data-stream-collection>
"""


def test_normalize_severity_known_and_unknown():
    assert _normalize_severity("high") == "HIGH"
    assert _normalize_severity("MEDIUM") == "MEDIUM"
    assert _normalize_severity(None) == "MEDIUM"
    assert _normalize_severity("unknown") == "MEDIUM"


def test_parse_xccdf_rules_extracts_content_and_refs():
    rules = parse_xccdf_rules(BARE_BENCHMARK)
    assert len(rules) == 1

    rule = rules[0]
    assert rule.rule_key == "xccdf_org.test_rule_sshd_disable_root_login"
    assert rule.title == "Disable SSH Root Login"
    assert rule.description == "The root user should never log in directly."
    assert rule.rationale == "Individual accountability requires named-user login."
    assert rule.severity == "MEDIUM"
    assert rule.standard_refs["cce"] == "CCE-80901-2"
    assert rule.standard_refs["https://www.cisecurity.org"] == "CIS 5.2.10"


def test_parse_xccdf_rules_missing_title_falls_back_to_rule_key():
    minimal = b"""<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2">
        <Rule id="xccdf_org.test_rule_no_title" severity="low"/>
    </Benchmark>"""
    rules = parse_xccdf_rules(minimal)
    assert rules[0].title == "xccdf_org.test_rule_no_title"


def test_parse_xccdf_profiles_only_selected_true():
    profiles = parse_xccdf_profiles(BARE_BENCHMARK)
    assert len(profiles) == 1

    profile = profiles[0]
    assert profile.profile_id == "xccdf_org.test_profile_cis_demo"
    assert profile.title == "CIS Demo Profile"
    assert profile.framework == "CIS"
    assert "xccdf_org.test_rule_sshd_disable_root_login" in profile.rule_keys
    assert "xccdf_org.test_rule_not_in_datastream" in profile.rule_keys
    assert "xccdf_org.test_rule_unselected" not in profile.rule_keys


def test_parse_xccdf_profile_framework_defaults_to_internal():
    doc = b"""<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2">
        <Profile id="xccdf_org.test_profile_custom">
            <title>Fully Custom Baseline</title>
        </Profile>
    </Benchmark>"""
    profiles = parse_xccdf_profiles(doc)
    assert profiles[0].framework == "INTERNAL"


def test_parse_xccdf_rules_finds_benchmark_inside_datastream_wrapper():
    rules = parse_xccdf_rules(DATASTREAM_WRAPPED)
    assert len(rules) == 1
    assert rules[0].rule_key == "xccdf_org.test_rule_wrapped"
    assert rules[0].severity == "HIGH"
