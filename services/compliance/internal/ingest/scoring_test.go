package ingest

import (
	"testing"

	"github.com/lokilinux/compliance/internal/storage"
)

func TestComputeCategoryScores_MixedResultsAcrossDomains(t *testing.T) {
	evaluations := []storage.EvaluationSummary{
		{Domain: "sshd", Result: "PASS"},             // security
		{Domain: "sshd", Result: "FAIL"},             // security
		{Domain: "pam", Result: "PASS"},              // security
		{Domain: "sysctl", Result: "PASS"},           // configuration
		{Domain: "sysctl", Result: "NOT_APPLICABLE"}, // configuration, excluded from denominator
		{Domain: "sysctl", Result: "ERROR"},          // configuration, excluded entirely
	}

	scores := computeCategoryScores(evaluations)

	byCategory := map[string]categoryScore{}
	for _, s := range scores {
		byCategory[s.category] = s
	}

	security := byCategory["security"]
	if security.passed != 2 || security.failed != 1 {
		t.Errorf("security = %+v, want passed=2 failed=1", security)
	}
	wantSecurityScore := 100.0 * 2 / 3
	if security.score != wantSecurityScore {
		t.Errorf("security.score = %v, want %v", security.score, wantSecurityScore)
	}

	configuration := byCategory["configuration"]
	if configuration.passed != 1 || configuration.failed != 0 || configuration.notApplicable != 1 {
		t.Errorf("configuration = %+v, want passed=1 failed=0 notApplicable=1", configuration)
	}
	if configuration.score != 100.0 {
		t.Errorf("configuration.score = %v, want 100 (1/1 passed, ERROR/NOT_APPLICABLE excluded)", configuration.score)
	}

	overall, ok := byCategory["overall"]
	if !ok {
		t.Fatal("expected a synthetic 'overall' category")
	}
	wantOverall := (wantSecurityScore + 100.0) / 2
	if overall.score != wantOverall {
		t.Errorf("overall.score = %v, want %v (mean of security+configuration)", overall.score, wantOverall)
	}
}

func TestComputeCategoryScores_EmptyInput(t *testing.T) {
	if scores := computeCategoryScores(nil); len(scores) != 0 {
		t.Errorf("got %v, want no scores for empty input", scores)
	}
}

func TestComputeCategoryScores_AllErrorNoScoreableRules(t *testing.T) {
	evaluations := []storage.EvaluationSummary{
		{Domain: "sshd", Result: "ERROR"},
		{Domain: "sshd", Result: "NOT_EVALUATED"},
	}
	scores := computeCategoryScores(evaluations)

	if len(scores) != 1 {
		t.Fatalf("got %d scores, want 1 (security only, no overall since nothing was scoreable): %+v", len(scores), scores)
	}
	if scores[0].category != "security" || scores[0].score != 0 {
		t.Errorf("got %+v, want security with score=0 (0/0 -> no divide, defaults to zero value)", scores[0])
	}
}

// TestComputeCategoryScores_Weighted locks the KTD4 weighted projection:
// 100 x sum(w_i*passed_i)/sum(w_i*(passed_i+failed_i)) with CRITICAL=10,
// HIGH=5, MEDIUM=2, LOW=1; UNKNOWN excluded from the denominator but
// visible as unknown_count; severity_breakdown records pass/fail per
// severity.
func TestComputeCategoryScores_Weighted(t *testing.T) {
	evaluations := []storage.EvaluationSummary{
		{Domain: "sshd", Result: "PASS", Severity: "CRITICAL"},      // w=10 earned
		{Domain: "sshd", Result: "FAIL", Severity: "MEDIUM"},        // w=2 applicable
		{Domain: "pam", Result: "FAIL", Severity: "HIGH"},           // w=5
		{Domain: "pam", Result: "PASS", Severity: "LOW"},            // w=1
		{Domain: "pam", Result: "UNKNOWN", Severity: "HIGH"},        // excluded from denominator
		{Domain: "sudo", Result: "NOT_APPLICABLE", Severity: "LOW"}, // excluded entirely
	}
	scores := computeCategoryScores(evaluations)

	byCategory := map[string]categoryScore{}
	for _, s := range scores {
		byCategory[s.category] = s
	}

	security := byCategory["security"]
	// passed weights 10+1=11, failed weights 2+5=7 → weighted = 100*11/18
	wantWeighted := 100.0 * 11 / 18
	if security.weightedScore != wantWeighted {
		t.Errorf("security.weightedScore = %v, want %v", security.weightedScore, wantWeighted)
	}
	if security.unknown != 1 {
		t.Errorf("security.unknown = %d, want 1 (UNKNOWN tracked, never a PASS)", security.unknown)
	}
	wantShare := float64(1) / float64(4+1+1+1) // unknown/(pass+fail+unknown+N.A.)
	if diff := security.unknownShare - wantShare; diff > 1e-9 || diff < -1e-9 {
		t.Errorf("security.unknownShare = %v, want %v", security.unknownShare, wantShare)
	}
	if got := security.breakdown["CRITICAL"]; got == nil || got["passed"] != 1 {
		t.Errorf("breakdown CRITICAL = %#v, want {passed:1}", got)
	}
	if got := security.breakdown["HIGH"]; got == nil || got["failed"] != 1 {
		t.Errorf("breakdown HIGH = %#v, want {failed:1}", got)
	}
}

// TestComputeCategoryScores_UnknownHeavySetNeverLooksComplete is the R5
// honesty guardrail golden: when every verdict is UNKNOWN, both scores stay
// zero and the unknown share is 1 — no partial-credit illusion possible.
func TestComputeCategoryScores_UnknownHeavySetNeverLooksComplete(t *testing.T) {
	evaluations := []storage.EvaluationSummary{
		{Domain: "sshd", Result: "UNKNOWN", Severity: "CRITICAL"},
		{Domain: "pam", Result: "UNKNOWN", Severity: "HIGH"},
	}
	scores := computeCategoryScores(evaluations)

	byCategory := map[string]categoryScore{}
	for _, s := range scores {
		byCategory[s.category] = s
	}
	sec := byCategory["security"]
	if sec.weightedScore != 0 || sec.score != 0 {
		t.Errorf("weighted=%v score=%v, want both 0 — nothing was judgeable", sec.weightedScore, sec.score)
	}
	if sec.unknownShare != 1.0 {
		t.Errorf("unknownShare = %v, want 1.0 (basis fully uncollected)", sec.unknownShare)
	}
	if sec.passed != 0 || sec.failed != 0 {
		t.Errorf("passed=%d failed=%d, want 0/0", sec.passed, sec.failed)
	}
}
