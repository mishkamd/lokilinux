// Package rules evaluates compliance_rules against an agent's normalized
// fact document. CEL (not OVAL/oscap) is the evaluation mechanism — see
// docs/compliance/07-POLICY-ENGINE.md §2 for why: CEL's sandboxing (no I/O,
// no unbounded loops, cost-limited evaluation) is exactly the guarantee
// needed to run bulk-imported check logic across a fleet without risking a
// malformed or malicious expression escaping its evaluation.
package rules

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"sync"

	"github.com/google/cel-go/cel"
	"lukechampine.com/blake3"

	"github.com/lokilinux/compliance/internal/scope"
)

// Result mirrors rule_evaluations.result (docs/compliance/01-DATA-MODEL.md §4).
type Result string

const (
	ResultPass          Result = "PASS"
	ResultFail          Result = "FAIL"
	ResultError         Result = "ERROR"
	ResultNotApplicable Result = "NOT_APPLICABLE"
	ResultNotEvaluated  Result = "NOT_EVALUATED"
	// ResultUnknown (Enterprise Compliance plan U4/KTD3): a declared
	// EvidencePath is absent from this snapshot's facts. Distinct from
	// ResultError (a check_expr/compile failure) — the rule itself is fine,
	// the collector just hasn't reported that fact yet. Never counted as
	// PASS anywhere (scoring, coverage, UI).
	ResultUnknown Result = "UNKNOWN"
)

// CheckSource mirrors compliance_rules.check_source.
type CheckSource string

const (
	CheckSourceCEL           CheckSource = "CEL"
	CheckSourceOVALUnmapped  CheckSource = "OVAL_UNMAPPED"
	CheckSourceOscapFallback CheckSource = "OSCAP_FALLBACK"
)

// Rule is the subset of a compliance_rules row the evaluator needs.
type Rule struct {
	ID             string
	CheckSource    CheckSource
	CheckExpr      string   // CEL source; empty when CheckSource != CEL
	PlatformFilter []string // compliance_rules.platform_filter; empty = every platform
	ExpectedValue  any      // compliance_rules.expected_value, decoded JSON; nil if unset
	// EvidencePaths are dotted paths into the facts document (e.g.
	// "sshd.PermitRootLogin") this rule's check_expr actually reads —
	// sourced from compliance_rule_resources rows with
	// resource_type='FACT_PATH' (docs/compliance §21, §40). Evidence is
	// built by extracting exactly these values, never the whole facts
	// document.
	EvidencePaths []string
}

// Verdict is the outcome of evaluating one rule against one fact document.
type Verdict struct {
	Result       Result
	Reason       string // set on ResultUnknown; explains why (plan U4/KTD3)
	ActualValue  any
	Evidence     map[string]any
	EvidenceHash string // blake3(canonical evidence JSON) — tamper-evidence per docs/compliance §21
	Err          error
}

// Evaluator checks one compliance rule against a fact document. platform is
// the agent's compliance_rules.platform_filter identifier (scope.PlatformID)
// — required so a rule scoped to rhel9 is never evaluated against an
// Ubuntu agent (docs/compliance §38). The only production implementation is
// CEL; the interface leaves room for a future OscapEvaluator
// (CheckSourceOscapFallback) without touching call sites.
type Evaluator interface {
	Evaluate(ctx context.Context, rule Rule, facts map[string]any, platform string) Verdict
}

// factsVar is the single top-level CEL variable every rule's check_expr is
// evaluated against, e.g. `facts.sshd.PermitRootLogin == "no"`.
const factsVar = "facts"

// CELEvaluator compiles and caches CEL programs per rule.ID — bulk fleet
// evaluation re-runs the same rule set against every agent's snapshot, so
// compiling once and reusing the program is the difference between a
// per-evaluation parse and a per-rule-lifetime one.
type CELEvaluator struct {
	env *cel.Env

	mu       sync.RWMutex
	programs map[string]cel.Program // rule.ID -> compiled program
}

// NewCELEvaluator builds the shared CEL environment. Facts are untyped
// (cel.DynType) since the fact document's shape varies per domain
// (sshd/sysctl/mounts/...) — the evaluator has no static schema for it.
func NewCELEvaluator() (*CELEvaluator, error) {
	env, err := cel.NewEnv(
		cel.Variable(factsVar, cel.MapType(cel.StringType, cel.DynType)),
	)
	if err != nil {
		return nil, fmt.Errorf("building CEL environment: %w", err)
	}
	return &CELEvaluator{env: env, programs: make(map[string]cel.Program)}, nil
}

func (e *CELEvaluator) Evaluate(ctx context.Context, rule Rule, facts map[string]any, platform string) Verdict {
	if !scope.PlatformApplicable(rule.PlatformFilter, platform) {
		return Verdict{
			Result: ResultNotApplicable,
			Evidence: map[string]any{
				"reason":          "platform_not_applicable",
				"agent_platform":  platform,
				"platform_filter": rule.PlatformFilter,
			},
		}
	}

	if rule.CheckSource != CheckSourceCEL {
		// OVAL_UNMAPPED / OSCAP_FALLBACK: never silently PASS. Coverage
		// tracking (docs/compliance/07-POLICY-ENGINE.md §3) depends on this
		// staying distinct from an actual evaluation outcome.
		return Verdict{Result: ResultNotEvaluated}
	}

	if missing := missingPaths(facts, rule.EvidencePaths); len(missing) > 0 {
		// A rule without any declared EvidencePaths has nothing to be
		// honest about, so it can never land here (len(missing) is
		// always 0 for an empty rule.EvidencePaths).
		const reason = "required fact not collected"
		return Verdict{
			Result: ResultUnknown,
			Reason: reason,
			Evidence: map[string]any{
				"reason":        reason,
				"missing_paths": missing,
			},
		}
	}

	prg, err := e.compiled(rule)
	if err != nil {
		return Verdict{Result: ResultError, Err: err}
	}

	out, _, err := prg.ContextEval(ctx, map[string]any{factsVar: facts})
	if err != nil {
		return Verdict{Result: ResultError, Err: fmt.Errorf("evaluating rule %s: %w", rule.ID, err)}
	}

	pass, ok := out.Value().(bool)
	if !ok {
		return Verdict{
			Result: ResultError,
			Err:    fmt.Errorf("rule %s: check_expr must return bool, got %T", rule.ID, out.Value()),
		}
	}

	actual := actualByPath(facts, rule.EvidencePaths)
	evidence := map[string]any{
		"fact_paths": rule.EvidencePaths,
		"actual":     actual,
		"source":     "lokilinux-agent",
	}
	if rule.ExpectedValue != nil {
		evidence["expected"] = rule.ExpectedValue
	}
	hash, hashErr := evidenceHash(evidence)
	if hashErr != nil {
		return Verdict{Result: ResultError, Err: fmt.Errorf("hashing evidence for rule %s: %w", rule.ID, hashErr)}
	}

	var actualValue any = actual
	if pass {
		return Verdict{Result: ResultPass, ActualValue: actualValue, Evidence: evidence, EvidenceHash: hash}
	}
	return Verdict{Result: ResultFail, ActualValue: actualValue, Evidence: evidence, EvidenceHash: hash}
}

// actualByPath extracts exactly the fact values a rule's check_expr reads —
// never the whole facts document (docs/compliance §4, §21: "never store
// only FAILED", but also never store more than what the check actually
// looked at). Missing paths are simply absent from the result rather than
// erroring — a rule whose evidence path doesn't (yet) exist in this
// snapshot still produced a real PASS/FAIL/ERROR verdict above; the
// evidence is best-effort annotation, not the source of truth for the result.
func actualByPath(facts map[string]any, paths []string) map[string]any {
	out := make(map[string]any, len(paths))
	for _, p := range paths {
		if v, ok := extractPath(facts, p); ok {
			out[p] = v
		}
	}
	return out
}

// missingPaths returns the subset of paths absent from facts, preserving
// rule.EvidencePaths order — the UNKNOWN precheck's honesty guardrail
// (plan U4/KTD3): a rule can only be evaluated if every fact it declared
// needing was actually collected.
func missingPaths(facts map[string]any, paths []string) []string {
	var missing []string
	for _, p := range paths {
		if _, ok := extractPath(facts, p); !ok {
			missing = append(missing, p)
		}
	}
	return missing
}

// extractPath walks a dot-separated path (e.g. "sshd.PermitRootLogin")
// through nested map[string]any levels, mirroring the shape
// encoding/json.Unmarshal produces for the canonical facts document.
func extractPath(facts map[string]any, dotted string) (any, bool) {
	var cur any = facts
	for _, seg := range strings.Split(dotted, ".") {
		m, ok := cur.(map[string]any)
		if !ok {
			return nil, false
		}
		cur, ok = m[seg]
		if !ok {
			return nil, false
		}
	}
	return cur, true
}

// evidenceHash is BLAKE3 over the evidence map's canonical (key-sorted, via
// encoding/json) JSON encoding — a stable fingerprint so evidence tampering
// after the fact is detectable (docs/compliance §21).
func evidenceHash(evidence map[string]any) (string, error) {
	body, err := json.Marshal(evidence)
	if err != nil {
		return "", err
	}
	sum := blake3.Sum256(body)
	return hex.EncodeToString(sum[:]), nil
}

// compiled returns the cached program for rule.ID, compiling and caching it
// on first use. Safe for concurrent use by the ingest worker pool
// (docs/compliance/02-GO-SERVICE.md §5).
func (e *CELEvaluator) compiled(rule Rule) (cel.Program, error) {
	e.mu.RLock()
	prg, ok := e.programs[rule.ID]
	e.mu.RUnlock()
	if ok {
		return prg, nil
	}

	e.mu.Lock()
	defer e.mu.Unlock()
	// Re-check under the write lock: another goroutine may have compiled
	// this same rule while we were waiting.
	if prg, ok := e.programs[rule.ID]; ok {
		return prg, nil
	}

	ast, issues := e.env.Compile(rule.CheckExpr)
	if issues != nil && issues.Err() != nil {
		return nil, fmt.Errorf("rule %s: check_expr compile error: %w", rule.ID, issues.Err())
	}
	if ast.OutputType() != cel.BoolType {
		return nil, fmt.Errorf("rule %s: check_expr must have bool output type, got %s", rule.ID, ast.OutputType())
	}

	prg, err := e.env.Program(ast)
	if err != nil {
		return nil, fmt.Errorf("rule %s: building CEL program: %w", rule.ID, err)
	}

	e.programs[rule.ID] = prg
	return prg, nil
}
