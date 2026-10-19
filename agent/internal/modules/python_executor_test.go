package modules

import (
	"context"
	"strings"
	"testing"
)

func TestPythonExecutor_ScriptOverCap_Rejected(t *testing.T) {
	e := NewPythonExecutor()
	oversized := strings.Repeat("a", maxPythonScriptBytes+1)

	result := e.Execute(context.Background(), "job-1", oversized, 0)

	if result.ExitCode != 1 {
		t.Fatalf("ExitCode = %d, want 1", result.ExitCode)
	}
	if !strings.Contains(result.Error, "exceeds") {
		t.Fatalf("Error = %q, want it to mention the cap", result.Error)
	}
}

func TestPythonExecutor_CheckSyntax_ScriptOverCap_Rejected(t *testing.T) {
	e := NewPythonExecutor()
	oversized := strings.Repeat("a", maxPythonScriptBytes+1)

	result := e.CheckSyntax(context.Background(), "job-1", oversized, 0)

	if result.ExitCode != 1 {
		t.Fatalf("ExitCode = %d, want 1", result.ExitCode)
	}
	if !strings.Contains(result.Error, "exceeds") {
		t.Fatalf("Error = %q, want it to mention the cap", result.Error)
	}
}
