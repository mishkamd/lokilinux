package rules

import (
	"context"
	"testing"
)

func newTestEvaluator(t *testing.T) *CELEvaluator {
	t.Helper()
	e, err := NewCELEvaluator()
	if err != nil {
		t.Fatalf("NewCELEvaluator() error = %v", err)
	}
	return e
}

func TestEvaluate_Pass(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "sshd_disable_root_login", CheckSource: CheckSourceCEL, CheckExpr: `facts.sshd.PermitRootLogin == "no"`}
	facts := map[string]any{"sshd": map[string]any{"PermitRootLogin": "no"}}

	v := e.Evaluate(context.Background(), rule, facts, "")
	if v.Result != ResultPass {
		t.Errorf("Result = %v, want PASS (err=%v)", v.Result, v.Err)
	}
}

func TestEvaluate_Fail(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "sshd_disable_root_login", CheckSource: CheckSourceCEL, CheckExpr: `facts.sshd.PermitRootLogin == "no"`}
	facts := map[string]any{"sshd": map[string]any{"PermitRootLogin": "yes"}}

	v := e.Evaluate(context.Background(), rule, facts, "")
	if v.Result != ResultFail {
		t.Errorf("Result = %v, want FAIL (err=%v)", v.Result, v.Err)
	}
}

// TestEvaluate_NestedMapKeyWithDot locks the sysctl access pattern from
// docs/compliance/07-POLICY-ENGINE.md §2 — sysctl keys contain dots
// (net.ipv4.ip_forward), so they must be read via index syntax, not field
// selection.
func TestEvaluate_NestedMapKeyWithDot(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "sysctl_ip_forward_disabled", CheckSource: CheckSourceCEL, CheckExpr: `facts.sysctl["net.ipv4.ip_forward"] == "0"`}
	facts := map[string]any{"sysctl": map[string]any{"net.ipv4.ip_forward": "0"}}

	v := e.Evaluate(context.Background(), rule, facts, "")
	if v.Result != ResultPass {
		t.Errorf("Result = %v, want PASS (err=%v)", v.Result, v.Err)
	}
}

// TestEvaluate_ExistsMacroOverList locks the mount-options check pattern —
// facts.mounts is a list of maps, and CEL's exists() macro is how a rule
// checks "some mount has this property" without a manual loop.
func TestEvaluate_ExistsMacroOverList(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{
		ID:          "tmp_mounted_noexec",
		CheckSource: CheckSourceCEL,
		CheckExpr:   `facts.mounts.exists(m, m.target == "/tmp" && "noexec" in m.options)`,
	}
	facts := map[string]any{
		"mounts": []any{
			map[string]any{"target": "/", "options": []any{"rw"}},
			map[string]any{"target": "/tmp", "options": []any{"rw", "noexec", "nosuid"}},
		},
	}

	v := e.Evaluate(context.Background(), rule, facts, "")
	if v.Result != ResultPass {
		t.Errorf("Result = %v, want PASS (err=%v)", v.Result, v.Err)
	}

	// Same rule, /tmp missing noexec -> FAIL.
	facts["mounts"] = []any{
		map[string]any{"target": "/tmp", "options": []any{"rw"}},
	}
	v = e.Evaluate(context.Background(), rule, facts, "")
	if v.Result != ResultFail {
		t.Errorf("Result = %v, want FAIL (err=%v)", v.Result, v.Err)
	}
}

func TestEvaluate_OVALUnmapped_NeverSilentlyPasses(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "some_stig_rule_without_cel_mapping", CheckSource: CheckSourceOVALUnmapped}

	v := e.Evaluate(context.Background(), rule, map[string]any{}, "")
	if v.Result != ResultNotEvaluated {
		t.Errorf("Result = %v, want NOT_EVALUATED for an OVAL_UNMAPPED rule", v.Result)
	}
	if v.Err != nil {
		t.Errorf("Err = %v, want nil — an unmapped rule is not a failure", v.Err)
	}
}

func TestEvaluate_OscapFallback_AlsoNeverSilentlyPasses(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "some_rule_needing_real_oscap", CheckSource: CheckSourceOscapFallback}

	v := e.Evaluate(context.Background(), rule, map[string]any{}, "")
	if v.Result != ResultNotEvaluated {
		t.Errorf("Result = %v, want NOT_EVALUATED for an OSCAP_FALLBACK rule (this evaluator never shells out)", v.Result)
	}
}

func TestEvaluate_CompileError_ReturnsError(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "broken_rule", CheckSource: CheckSourceCEL, CheckExpr: `facts.sshd.PermitRootLogin ===`}

	v := e.Evaluate(context.Background(), rule, map[string]any{}, "")
	if v.Result != ResultError {
		t.Errorf("Result = %v, want ERROR for unparseable check_expr", v.Result)
	}
	if v.Err == nil {
		t.Error("Err = nil, want a compile error")
	}
}

// TestEvaluate_NonBoolOutput_RejectedAtCompileTime guards a malformed rule
// import from ever producing a nonsensical "truthy string" evaluation
// instead of a real PASS/FAIL — checked once, at compile time, not per-run.
func TestEvaluate_NonBoolOutput_RejectedAtCompileTime(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "wrong_output_type", CheckSource: CheckSourceCEL, CheckExpr: `facts.sshd.PermitRootLogin`}
	facts := map[string]any{"sshd": map[string]any{"PermitRootLogin": "no"}}

	v := e.Evaluate(context.Background(), rule, facts, "")
	if v.Result != ResultError {
		t.Errorf("Result = %v, want ERROR for a non-bool check_expr", v.Result)
	}
}

// TestEvaluate_MissingFactsDoNotPanic — a domain the agent hasn't reported
// yet (nil/missing key) must degrade to ERROR, not crash the evaluator that
// every other agent's evaluation shares.
func TestEvaluate_MissingFactsDoNotPanic(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "sshd_disable_root_login", CheckSource: CheckSourceCEL, CheckExpr: `facts.sshd.PermitRootLogin == "no"`}

	v := e.Evaluate(context.Background(), rule, map[string]any{}, "") // no "sshd" key at all
	if v.Result != ResultError {
		t.Errorf("Result = %v, want ERROR when the referenced domain is absent from facts", v.Result)
	}
}

// TestEvaluate_ProgramCacheReused locks that repeated evaluations of the
// same rule.ID reuse the compiled program rather than recompiling — the
// whole reason for the cache (docs/compliance/02-GO-SERVICE.md §3: bulk
// fleet evaluation re-runs the same rule set per agent).
func TestEvaluate_ProgramCacheReused(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "cached_rule", CheckSource: CheckSourceCEL, CheckExpr: `facts.x == "y"`}

	_ = e.Evaluate(context.Background(), rule, map[string]any{"x": "y"}, "")
	if len(e.programs) != 1 {
		t.Fatalf("programs cached = %d, want 1 after first evaluation", len(e.programs))
	}

	_ = e.Evaluate(context.Background(), rule, map[string]any{"x": "z"}, "")
	if len(e.programs) != 1 {
		t.Errorf("programs cached = %d, want still 1 after second evaluation of the same rule", len(e.programs))
	}
}

// TestEvaluate_PlatformFilter_NotApplicable locks that a rule scoped to
// platforms not matching the agent's returns NOT_APPLICABLE — never FAIL,
// so fleet-wide compliance % (docs/compliance §22) doesn't punish an Ubuntu
// agent for a rocky9-only rule.
func TestEvaluate_PlatformFilter_NotApplicable(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{
		ID: "rocky_only_rule", CheckSource: CheckSourceCEL,
		CheckExpr: `facts.sshd.PermitRootLogin == "no"`, PlatformFilter: []string{"rocky9", "rhel9"},
	}
	facts := map[string]any{"sshd": map[string]any{"PermitRootLogin": "yes"}}

	v := e.Evaluate(context.Background(), rule, facts, "ubuntu22")
	if v.Result != ResultNotApplicable {
		t.Errorf("Result = %v, want NOT_APPLICABLE for a platform not in platform_filter", v.Result)
	}
}

// TestEvaluate_PlatformFilter_Applicable locks that a matching platform (any
// case) still runs the check normally.
func TestEvaluate_PlatformFilter_Applicable(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{
		ID: "rocky_only_rule2", CheckSource: CheckSourceCEL,
		CheckExpr: `facts.sshd.PermitRootLogin == "no"`, PlatformFilter: []string{"rocky9"},
	}
	facts := map[string]any{"sshd": map[string]any{"PermitRootLogin": "no"}}

	v := e.Evaluate(context.Background(), rule, facts, "ROCKY9")
	if v.Result != ResultPass {
		t.Errorf("Result = %v, want PASS on a matching platform (case-insensitive)", v.Result)
	}
}

// TestEvaluate_PlatformFilter_EmptyMeansEveryPlatform locks that a rule with
// no platform_filter runs regardless of the agent's platform (most rules —
// sysctl, users, sudo — aren't OS-specific).
func TestEvaluate_PlatformFilter_EmptyMeansEveryPlatform(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{ID: "universal_rule", CheckSource: CheckSourceCEL, CheckExpr: `facts.sshd.PermitRootLogin == "no"`}
	facts := map[string]any{"sshd": map[string]any{"PermitRootLogin": "no"}}

	v := e.Evaluate(context.Background(), rule, facts, "some_unknown_platform")
	if v.Result != ResultPass {
		t.Errorf("Result = %v, want PASS — empty platform_filter must apply everywhere", v.Result)
	}
}

// TestEvaluate_Evidence_OnlyExtractsDeclaredPaths locks that evidence
// contains exactly the fact values named in EvidencePaths, never the whole
// facts document (the gap this rewrite closes — see docs/compliance §21).
func TestEvaluate_Evidence_OnlyExtractsDeclaredPaths(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{
		ID: "sshd_disable_root_login", CheckSource: CheckSourceCEL,
		CheckExpr: `facts.sshd.PermitRootLogin == "no"`, EvidencePaths: []string{"sshd.PermitRootLogin"},
		ExpectedValue: "no",
	}
	facts := map[string]any{
		"sshd": map[string]any{"PermitRootLogin": "yes", "PasswordAuthentication": "no"},
	}

	v := e.Evaluate(context.Background(), rule, facts, "")
	if v.Result != ResultFail {
		t.Fatalf("Result = %v, want FAIL", v.Result)
	}
	actual, ok := v.Evidence["actual"].(map[string]any)
	if !ok {
		t.Fatalf("Evidence[actual] = %#v, want map[string]any", v.Evidence["actual"])
	}
	if actual["sshd.PermitRootLogin"] != "yes" {
		t.Errorf("actual[sshd.PermitRootLogin] = %v, want yes", actual["sshd.PermitRootLogin"])
	}
	if _, leaked := actual["sshd.PasswordAuthentication"]; leaked {
		t.Error("evidence must not contain fact paths outside EvidencePaths")
	}
	if v.Evidence["expected"] != "no" {
		t.Errorf("Evidence[expected] = %v, want no", v.Evidence["expected"])
	}
	if v.EvidenceHash == "" {
		t.Error("EvidenceHash must be set for a real evaluation")
	}
}

// TestEvaluate_EvidenceHash_StableAndSensitive locks that the same
// evidence hashes identically twice, and that a different actual value
// changes the hash — the tamper-evidence property docs/compliance §21 asks
// for.
func TestEvaluate_EvidenceHash_StableAndSensitive(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{
		ID: "sshd_disable_root_login", CheckSource: CheckSourceCEL,
		CheckExpr: `facts.sshd.PermitRootLogin == "no"`, EvidencePaths: []string{"sshd.PermitRootLogin"},
	}

	v1 := e.Evaluate(context.Background(), rule, map[string]any{"sshd": map[string]any{"PermitRootLogin": "yes"}}, "")
	v2 := e.Evaluate(context.Background(), rule, map[string]any{"sshd": map[string]any{"PermitRootLogin": "yes"}}, "")
	if v1.EvidenceHash != v2.EvidenceHash {
		t.Errorf("identical evidence hashed differently: %s vs %s", v1.EvidenceHash, v2.EvidenceHash)
	}

	v3 := e.Evaluate(context.Background(), rule, map[string]any{"sshd": map[string]any{"PermitRootLogin": "no"}}, "")
	if v1.EvidenceHash == v3.EvidenceHash {
		t.Error("different actual values must hash differently")
	}
}

// TestEvaluate_MissingEvidencePath_OmittedNotErrored locks that an
// EvidencePaths entry absent from this snapshot's facts is simply left out
// of the evidence map rather than failing the whole evaluation — the CEL
// check itself already handles a missing fact (ERROR), evidence extraction
// is best-effort on top of that real result.
func TestEvaluate_MissingEvidencePath_OmittedNotErrored(t *testing.T) {
	e := newTestEvaluator(t)
	rule := Rule{
		ID: "checks_present_field_only", CheckSource: CheckSourceCEL,
		CheckExpr:     `facts.sshd.PermitRootLogin == "no"`,
		EvidencePaths: []string{"sshd.PermitRootLogin", "sshd.NeverCollectedField"},
	}
	facts := map[string]any{"sshd": map[string]any{"PermitRootLogin": "no"}}

	v := e.Evaluate(context.Background(), rule, facts, "")
	if v.Result != ResultPass {
		t.Fatalf("Result = %v, want PASS", v.Result)
	}
	actual := v.Evidence["actual"].(map[string]any)
	if len(actual) != 1 {
		t.Errorf("actual = %#v, want exactly 1 entry (missing path omitted, not errored)", actual)
	}
}
