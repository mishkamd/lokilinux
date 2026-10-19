package modules

import (
	"context"
	"os"
	"testing"
)

// TestJobExecutor_UsesRestrictedWorkDir asserts the side effect Execute
// must produce regardless of whether systemd-run itself succeeds in this
// sandbox (root/D-Bus permissions vary by CI environment) — the restricted
// working directory (plan P5) gets created before dispatch.
func TestJobExecutor_UsesRestrictedWorkDir(t *testing.T) {
	original := bashWorkDir
	bashWorkDir = t.TempDir() + "/job-workdir" // real path needs root; point at a writable temp dir instead
	defer func() { bashWorkDir = original }()

	e := NewJobExecutor()
	e.Execute(context.Background(), "job-1", "true", 2)

	info, err := os.Stat(bashWorkDir)
	if err != nil {
		t.Fatalf("bashWorkDir was not created: %v", err)
	}
	if !info.IsDir() {
		t.Fatalf("bashWorkDir exists but is not a directory")
	}
}

func TestJobExecutor_Execute_RejectsEmptyCommand(t *testing.T) {
	e := NewJobExecutor()
	result := e.Execute(context.Background(), "job-1", "", 5)
	if result.ExitCode != 1 {
		t.Fatalf("ExitCode = %d, want 1 for empty command", result.ExitCode)
	}
}
