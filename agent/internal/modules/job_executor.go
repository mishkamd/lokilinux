package modules

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
	"syscall"
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

// Execute runs command under /bin/sh with optional timeout.
// timeoutSec ≤ 0 means the caller's ctx deadline applies.
func (e *JobExecutor) Execute(ctx context.Context, jobID, command string, timeoutSec int) JobResult {
	start := time.Now()

	if err := validateCommand(command); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: msSince(start)}
	}

	if timeoutSec > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, time.Duration(timeoutSec)*time.Second)
		defer cancel()
	}

	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", command)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process != nil {
			// kill the entire process group so shell children don't outlive their parent
			return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		}
		return nil
	}
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	runErr := cmd.Run()

	code := 0
	errMsg := ""
	if cmd.ProcessState != nil {
		code = cmd.ProcessState.ExitCode()
	}
	if runErr != nil && code == 0 {
		errMsg = runErr.Error()
		code = 1
	}

	return JobResult{
		JobID:      jobID,
		ExitCode:   code,
		Stdout:     truncateOutput(stdout.String(), e.maxOutputBytes),
		Stderr:     truncateOutput(stderr.String(), e.maxOutputBytes),
		DurationMs: msSince(start),
		Error:      errMsg,
	}
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
