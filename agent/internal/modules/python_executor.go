package modules

import (
	"context"
	"os/exec"
	"time"
)

// PythonExecutor runs Python scripts via python3 -c <script> — no shell,
// argv-based dispatch via runViaSystemdRunArgv (same sandbox escape as
// AnsibleExecutor). Output cap matches other executors (4 MB).
type PythonExecutor struct {
	maxOutputBytes int
	binary         string
}

func NewPythonExecutor() *PythonExecutor {
	return &PythonExecutor{maxOutputBytes: 4 * 1024 * 1024, binary: "python3"}
}

// Execute runs script via python3 -c under systemd-run. timeoutSec ≤ 0 falls
// through to runSystemdRunUnit's own 3600s default.
func (e *PythonExecutor) Execute(ctx context.Context, jobID, script string, timeoutSec int) JobResult {
	start := time.Now()

	if _, err := exec.LookPath(e.binary); err != nil {
		return JobResult{
			JobID: jobID, ExitCode: 1,
			Error:      "python3 not installed on target (python3 not found in PATH)",
			DurationMs: msSince(start),
		}
	}

	if script == "" {
		return JobResult{
			JobID: jobID, ExitCode: 1,
			Error:      "empty python script",
			DurationMs: msSince(start),
		}
	}

	argv := []string{e.binary, "-c", script}
	result := runViaSystemdRunArgv(ctx, jobID, argv, "", timeoutSec, e.maxOutputBytes)
	result.DurationMs = msSince(start)
	return result
}
