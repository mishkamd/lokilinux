package modules

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
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
// Output is captured via -p StandardOutput=file:/StandardError=file:, NOT
// --pipe. This was the load-bearing finding of a long live debugging
// session: --pipe (passing this process's own stdout/stderr fds to the
// transient unit over the StartTransientUnit D-Bus call) reliably gets the
// bus connection reset when the caller's stdout/stderr are Go-created pipes
// (anything other than a real inherited terminal/socket fd) — reproduced
// down to a 20-line Go program with zero hardening directives at all, so
// it's not about the sandbox, NoNewPrivileges, or cgroups; it's specifically
// --pipe plus Go's os/exec output capture. Redirecting to files via unit
// properties sidesteps fd-passing over D-Bus entirely and just works.
//
// --wait makes systemd-run's own exit code mirror the unit's real exit code
// (documented systemd behavior since v232). --collect unloads the transient
// unit once it's done instead of leaving it around. RuntimeMaxSec is
// systemd's own timeout enforcement on the spawned unit — the primary bound
// here, since killing our local systemd-run client (via ctx cancellation)
// does not reliably stop the remote unit it started.

// jobOutputDir holds the per-job stdout/stderr files systemd writes into —
// real (non-PrivateTmp) path, so the spawned unit (outside the agent's
// mount namespace) and the agent reading the result afterward agree on it.
const jobOutputDir = "/var/lib/lokilinux/job-output"

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

	if err := os.MkdirAll(jobOutputDir, 0700); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: msSince(start)}
	}
	outFile := filepath.Join(jobOutputDir, jobID+".stdout")
	errFile := filepath.Join(jobOutputDir, jobID+".stderr")
	os.Remove(outFile) // stale file from a previous run with this job_id would otherwise be read back below
	os.Remove(errFile)
	defer os.Remove(outFile)
	defer os.Remove(errFile)

	args := []string{
		"--wait", "--quiet", "--collect",
		"-p", "RuntimeMaxSec=" + strconv.Itoa(timeoutSec),
		"-p", "StandardOutput=file:" + outFile,
		"-p", "StandardError=file:" + errFile,
	}
	if workDir != "" {
		args = append(args, "-p", "WorkingDirectory="+workDir)
	}
	args = append(args, "--")
	args = append(args, argv...)

	// Captures systemd-run's OWN diagnostics (e.g. it failing to even start
	// the unit) — separate from the unit's actual output, read from
	// outFile/errFile below once the unit has run.
	var metaOut []byte
	cmd := exec.CommandContext(ctx, "systemd-run", args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process != nil {
			return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		}
		return nil
	}

	metaOut, runErr := cmd.CombinedOutput()

	code := 0
	errMsg := ""
	if cmd.ProcessState != nil {
		code = cmd.ProcessState.ExitCode()
	}
	if runErr != nil && code == 0 {
		errMsg = runErr.Error()
		code = 1
	}

	stdout, _ := os.ReadFile(outFile)
	stderr, _ := os.ReadFile(errFile)
	stderrStr := string(stderr)
	if len(metaOut) > 0 {
		// systemd-run itself reported something (typically only happens
		// when it failed to start the unit at all, so outFile/errFile are
		// empty) — surface it, it's the only diagnostic available then.
		stderrStr = fmt.Sprintf("%s%s", stderrStr, string(metaOut))
	}

	return JobResult{
		JobID:      jobID,
		ExitCode:   code,
		Stdout:     truncateOutput(string(stdout), maxOutputBytes),
		Stderr:     truncateOutput(stderrStr, maxOutputBytes),
		DurationMs: msSince(start),
		Error:      errMsg,
	}
}
