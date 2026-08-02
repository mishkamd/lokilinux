package modules

import (
	"context"
	"fmt"
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
}

// JobExecutor runs shell commands in a subprocess with timeout and output capture.
type JobExecutor struct {
	maxOutputBytes int
}

func NewJobExecutor() *JobExecutor {
	return &JobExecutor{maxOutputBytes: 4 * 1024 * 1024} // 4 MB output cap per stream
}

// Execute runs command via systemd-run (escaping the agent's own sandbox —
// see systemd_run.go) with optional timeout.
// timeoutSec ≤ 0 means the config default (3600s) applies.
func (e *JobExecutor) Execute(ctx context.Context, jobID, command string, timeoutSec int) JobResult {
	return runViaSystemdRun(ctx, jobID, command, timeoutSec, e.maxOutputBytes)
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
