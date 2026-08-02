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
