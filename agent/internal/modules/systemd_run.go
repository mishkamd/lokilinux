package modules

import (
	"bytes"
	"context"
	"os/exec"
	"strconv"
	"syscall"
	"time"
)

// Both runViaSystemdRun and runViaSystemdRunArgv escape the agent's own
// mount-namespace sandbox (ProtectSystem=strict, PrivateTmp) via a transient
// systemd unit that PID1 spawns fresh, outside that namespace — the same
// way any systemctl-started unit escapes a caller's private mounts. The
// agent's own hardening is left in place; this only routes host-mutating
// job execution (package updates, ansible, arbitrary shell jobs) around it,
// since ProtectSystem=strict makes writing packages into /usr, running
// ansible tasks, etc. impossible from inside the agent's own namespace —
// confirmed live: dnf getting past /var/log only reaches a half-finished
// rpm transaction before dying on /usr, not a working update.
//
// --pipe wires the transient unit's stdin/stdout/stderr straight to this
// systemd-run client, so output capture works exactly like exec'ing the
// command directly. --wait makes systemd-run's own exit code mirror the
// unit's real exit code (documented systemd behavior since v232). --collect
// unloads the transient unit once it's done instead of leaving it around.
//
// RuntimeMaxSec is systemd's own timeout enforcement on the spawned unit —
// the primary bound here, since killing our local systemd-run client (via
// ctx cancellation) does not reliably stop the remote unit it started.

// runViaSystemdRun executes `command` under /bin/sh -c. Only for callers
// whose command is either fixed or built from trusted, well-formed parts
// (e.g. package manager names) — never for job payloads that carry
// arbitrary untrusted content, see runViaSystemdRunArgv for that case.
func runViaSystemdRun(ctx context.Context, jobID, command string, timeoutSec, maxOutputBytes int) JobResult {
	if err := validateCommand(command); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: 0}
	}
	return runSystemdRunUnit(ctx, jobID, []string{"/bin/sh", "-c", command}, "", timeoutSec, maxOutputBytes)
}

// runViaSystemdRunArgv executes argv directly — no shell involved at any
// point, so untrusted content (e.g. an ansible playbook's own files, only
// ever referenced here by path) can never be interpreted as shell syntax.
// workDir sets the transient unit's working directory (e.g. so ansible
// resolves roles/ next to the playbook); pass "" to leave it unset.
func runViaSystemdRunArgv(ctx context.Context, jobID string, argv []string, workDir string, timeoutSec, maxOutputBytes int) JobResult {
	return runSystemdRunUnit(ctx, jobID, argv, workDir, timeoutSec, maxOutputBytes)
}

func runSystemdRunUnit(ctx context.Context, jobID string, argv []string, workDir string, timeoutSec, maxOutputBytes int) JobResult {
	start := time.Now()

	if timeoutSec <= 0 {
		timeoutSec = 3600 // config default, mirrors manager.go's JobExecution.TimeoutSeconds fallback
	}
	var cancel context.CancelFunc
	ctx, cancel = context.WithTimeout(ctx, time.Duration(timeoutSec)*time.Second)
	defer cancel()

	args := []string{
		"--pipe", "--wait", "--quiet", "--collect",
		"-p", "RuntimeMaxSec=" + strconv.Itoa(timeoutSec),
	}
	if workDir != "" {
		args = append(args, "-p", "WorkingDirectory="+workDir)
	}
	args = append(args, "--")
	args = append(args, argv...)

	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, "systemd-run", args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process != nil {
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
		Stdout:     truncateOutput(stdout.String(), maxOutputBytes),
		Stderr:     truncateOutput(stderr.String(), maxOutputBytes),
		DurationMs: msSince(start),
		Error:      errMsg,
	}
}
