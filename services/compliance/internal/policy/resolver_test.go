package policy

import (
	"testing"

	"github.com/google/uuid"

	"github.com/lokilinux/compliance/internal/storage"
)

func TestMatchingSetIDs_GlobalAlwaysMatches(t *testing.T) {
	globalID := uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
	attrs := storage.AgentAttributes{OsDistro: "rocky", OsVersion: "9.8"}
	assignments := []storage.PolicyAssignment{
		{PolicySetID: globalID, ScopeType: "GLOBAL", ScopeSelector: map[string]any{}},
	}

	got := MatchingSetIDs(attrs, assignments)
	if len(got) != 1 || got[0] != globalID {
		t.Fatalf("MatchingSetIDs = %v, want [%s]", got, globalID)
	}
}

func TestMatchingSetIDs_ScopedAssignmentFiltersByAttributes(t *testing.T) {
	rockyOnly := uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
	ubuntuOnly := uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2")
	attrs := storage.AgentAttributes{OsDistro: "rocky", OsVersion: "9"}
	assignments := []storage.PolicyAssignment{
		{PolicySetID: rockyOnly, ScopeType: "OS", ScopeSelector: map[string]any{"os_distro": "rocky"}},
		{PolicySetID: ubuntuOnly, ScopeType: "OS", ScopeSelector: map[string]any{"os_distro": "ubuntu"}},
	}

	got := MatchingSetIDs(attrs, assignments)
	if len(got) != 1 || got[0] != rockyOnly {
		t.Fatalf("MatchingSetIDs = %v, want only [%s] (ubuntu-scoped must not match a rocky agent)", got, rockyOnly)
	}
}

func TestMatchingSetIDs_MultipleMatchesAllReturned(t *testing.T) {
	globalID := uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
	envID := uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2")
	attrs := storage.AgentAttributes{Category: "Production"}
	assignments := []storage.PolicyAssignment{
		{PolicySetID: globalID, ScopeType: "GLOBAL", ScopeSelector: map[string]any{}},
		{PolicySetID: envID, ScopeType: "ENVIRONMENT", ScopeSelector: map[string]any{"environment": "production"}},
	}

	got := MatchingSetIDs(attrs, assignments)
	if len(got) != 2 {
		t.Fatalf("MatchingSetIDs = %v, want 2 matches (GLOBAL + ENVIRONMENT both apply)", got)
	}
}

func TestMatchingSetIDs_NoMatchReturnsEmpty(t *testing.T) {
	attrs := storage.AgentAttributes{OsDistro: "ubuntu"}
	assignments := []storage.PolicyAssignment{
		{PolicySetID: uuid.New(), ScopeType: "OS", ScopeSelector: map[string]any{"os_distro": "rocky"}},
	}

	got := MatchingSetIDs(attrs, assignments)
	if len(got) != 0 {
		t.Fatalf("MatchingSetIDs = %v, want empty", got)
	}
}
