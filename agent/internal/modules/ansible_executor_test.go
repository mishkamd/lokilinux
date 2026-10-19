package modules

import (
	"context"
	"strings"
	"testing"
)

func TestAnsibleExecutor_PlaybookOverCap_Rejected(t *testing.T) {
	e := NewAnsibleExecutor()
	oversized := strings.Repeat("a", maxPlaybookBytes+1)

	result := e.Execute(context.Background(), "job-1", oversized, nil, nil, 0, false)

	if result.ExitCode != 1 {
		t.Fatalf("ExitCode = %d, want 1", result.ExitCode)
	}
	if !strings.Contains(result.Error, "exceeds") {
		t.Fatalf("Error = %q, want it to mention the cap", result.Error)
	}
}

func TestAnsibleExecutor_RolesOverCap_Rejected(t *testing.T) {
	e := NewAnsibleExecutor()
	roles := map[string]any{
		"big-role": map[string]any{
			"tasks/main.yml": strings.Repeat("a", maxPlaybookBytes+1),
		},
	}

	result := e.Execute(context.Background(), "job-1", "- hosts: localhost\n", nil, roles, 0, false)

	if result.ExitCode != 1 {
		t.Fatalf("ExitCode = %d, want 1", result.ExitCode)
	}
	if !strings.Contains(result.Error, "exceeds") {
		t.Fatalf("Error = %q, want it to mention the cap", result.Error)
	}
}

func TestAnsibleExecutor_CapIsCumulativeAcrossPlaybookAndRoles(t *testing.T) {
	e := NewAnsibleExecutor()
	half := maxPlaybookBytes/2 + 1
	roles := map[string]any{
		"role-a": map[string]any{
			"tasks/main.yml": strings.Repeat("a", half),
		},
	}

	// Neither the playbook nor the role alone exceeds the cap, but together they do.
	result := e.Execute(context.Background(), "job-1", strings.Repeat("b", half), nil, roles, 0, false)

	if result.ExitCode != 1 {
		t.Fatalf("ExitCode = %d, want 1 (cumulative cap should have tripped)", result.ExitCode)
	}
	if !strings.Contains(result.Error, "exceeds") {
		t.Fatalf("Error = %q, want it to mention the cap", result.Error)
	}
}

func TestRolesTotalSize(t *testing.T) {
	roles := map[string]any{
		"role-a": map[string]any{
			"tasks/main.yml":    "1234",
			"defaults/main.yml": "12",
		},
		"role-b": map[string]any{
			"tasks/main.yml": "123",
		},
		// Malformed entries (wrong types) must be ignored, not panic.
		"role-c": "not-a-map",
	}
	if got := rolesTotalSize(roles); got != 9 {
		t.Fatalf("rolesTotalSize = %d, want 9", got)
	}
}
