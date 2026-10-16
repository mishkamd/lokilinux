package modules

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"
)

// JobResult holds the outcome of a single job execution.
type JobResult struct {
	JobID      string
	ExitCode   int
	Stdout     string
	Stderr     string
	DurationMs int64
	Error      string // non-empty when the subprocess couldn't be started
	// Audit fields (plan P10) — populated by manager.go after Execute
	// returns, from the security.Registry capability lookup and the job's
	// signed envelope (when present). Empty when not applicable (e.g.
	// unsigned/non-privileged jobs have no PolicyID).
	Capability string
	Risk       string
	PolicyID   string
}

// bashWorkDir is EXEC_BASH's restricted working directory (plan P5) —
// every shell job runs rooted here instead of inheriting the agent
// process's own cwd. A var (not const) so tests can point it at a temp
// dir — the real path requires root (/var/lib/lokilinux is root:root 755).
var bashWorkDir = "/var/lib/lokilinux/job-workdir"

// JobExecutor runs shell commands in a subprocess with timeout and output capture.
type JobExecutor struct {
	maxOutputBytes int
}

func NewJobExecutor() *JobExecutor {
	return &JobExecutor{maxOutputBytes: 4 * 1024 * 1024} // 4 MB output cap per stream
}

// Execute runs command via systemd-run (escaping the agent's own sandbox —
// see systemd_run.go) with optional timeout, rooted in a restricted working
// directory (plan P5) rather than inheriting the agent's own cwd.
// timeoutSec ≤ 0 means the config default (3600s) applies.
func (e *JobExecutor) Execute(ctx context.Context, jobID, command string, timeoutSec int) JobResult {
	if err := validateCommand(command); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error()}
	}
	if err := os.MkdirAll(bashWorkDir, 0700); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error()}
	}
	return runSystemdRunUnit(ctx, jobID, []string{"/bin/sh", "-c", command}, bashWorkDir, timeoutSec, e.maxOutputBytes, &ProfileArbitraryCode)
}

// CheckSyntax validates command without running it — `sh -n -c <command>`
// parses the script and reports syntax errors, executing nothing (POSIX -n:
// "Read commands and check them for syntax errors, but do not execute
// them"). command is passed as a single argv element via
// runViaSystemdRunArgv, not interpolated into a shell string, so this has
// the same injection-safety as Execute itself — it just never runs anything.
// This is the shell half of remediation dry-run (docs/compliance §13, §14):
// a real syntax check, not a no-op stand-in.
func (e *JobExecutor) CheckSyntax(ctx context.Context, jobID, command string, timeoutSec int) JobResult {
	if err := validateCommand(command); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error()}
	}
	argv := []string{"sh", "-n", "-c", command}
	return runViaSystemdRunArgv(ctx, jobID, argv, "", timeoutSec, e.maxOutputBytes)
}

func validateCommand(command string) error {
	if strings.TrimSpace(command) == "" {
		return fmt.Errorf("empty command")
	}
	return nil
}

func truncateOutput(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max]
}

func msSince(t time.Time) int64 { return time.Since(t).Milliseconds() }
