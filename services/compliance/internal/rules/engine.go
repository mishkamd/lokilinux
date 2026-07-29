// Package rules evaluates compliance_rules against an agent's normalized
// fact document. CEL (not OVAL/oscap) is the evaluation mechanism — see
// docs/compliance/07-POLICY-ENGINE.md §2 for why: CEL's sandboxing (no I/O,
// no unbounded loops, cost-limited evaluation) is exactly the guarantee
// needed to run bulk-imported check logic across a fleet without risking a
// malformed or malicious expression escaping its evaluation.
package rules

import (
	"context"
	"fmt"
	"sync"

	"github.com/google/cel-go/cel"
)

// Result mirrors rule_evaluations.result (docs/compliance/01-DATA-MODEL.md §4).
type Result string

const (
	ResultPass          Result = "PASS"
	ResultFail          Result = "FAIL"
	ResultError         Result = "ERROR"
	ResultNotApplicable Result = "NOT_APPLICABLE"
	ResultNotEvaluated  Result = "NOT_EVALUATED"
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
	ID          string
	CheckSource CheckSource
	CheckExpr   string // CEL source; empty when CheckSource != CEL
}

// Verdict is the outcome of evaluating one rule against one fact document.
type Verdict struct {
	Result      Result
	ActualValue any
	Evidence    map[string]any
	Err         error
}

// Evaluator checks one compliance rule against a fact document. The only
// production implementation is CEL; the interface leaves room for a future
// OscapEvaluator (CheckSourceOscapFallback) without touching call sites.
type Evaluator interface {
	Evaluate(ctx context.Context, rule Rule, facts map[string]any) Verdict
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

func (e *CELEvaluator) Evaluate(ctx context.Context, rule Rule, facts map[string]any) Verdict {
	if rule.CheckSource != CheckSourceCEL {
		// OVAL_UNMAPPED / OSCAP_FALLBACK: never silently PASS. Coverage
		// tracking (docs/compliance/07-POLICY-ENGINE.md §3) depends on this
		// staying distinct from an actual evaluation outcome.
		return Verdict{Result: ResultNotEvaluated}
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

	evidence := map[string]any{"facts": facts}
	if pass {
		return Verdict{Result: ResultPass, ActualValue: true, Evidence: evidence}
	}
	return Verdict{Result: ResultFail, ActualValue: false, Evidence: evidence}
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
