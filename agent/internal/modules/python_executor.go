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

// checkScript parses argv[1] via the stdlib ast module and exits non-zero
// on a SyntaxError — passed as the -c program itself so it never changes
// even though the script under test does; the script under test arrives
// purely as data via sys.argv[1], never concatenated into source.
const checkScript = "import ast, sys\nast.parse(sys.argv[1])\n"

// CheckSyntax validates script without executing it — the Python half of
// remediation dry-run (docs/compliance §13, §14), mirroring
// JobExecutor.CheckSyntax's "real syntax check, not a no-op" approach.
// script reaches ast.parse as a plain argv element (sys.argv[1]), so
// arbitrary quotes/newlines in it can't break out of the -c program.
func (e *PythonExecutor) CheckSyntax(ctx context.Context, jobID, script string, timeoutSec int) JobResult {
	start := time.Now()
	if _, err := exec.LookPath(e.binary); err != nil {
		return JobResult{
			JobID: jobID, ExitCode: 1,
			Error:      "python3 not installed on target (python3 not found in PATH)",
			DurationMs: msSince(start),
		}
	}
	if script == "" {
		return JobResult{JobID: jobID, ExitCode: 1, Error: "empty python script", DurationMs: msSince(start)}
	}

	argv := []string{e.binary, "-c", checkScript, script}
	result := runViaSystemdRunArgv(ctx, jobID, argv, "", timeoutSec, e.maxOutputBytes)
	result.DurationMs = msSince(start)
	return result
}
