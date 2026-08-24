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
func runViaSystemdRun(ctx context.Context, jobID, command string, timeoutSec, maxOutputBytes int, profile ...*SandboxProfile) JobResult {
	if err := validateCommand(command); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: 0}
	}
	return runSystemdRunUnit(ctx, jobID, []string{"/bin/sh", "-c", command}, "", timeoutSec, maxOutputBytes, firstProfile(profile))
}

// runViaSystemdRunArgv executes argv directly — no shell involved at any
// point, so untrusted content (e.g. an ansible playbook's own files, only
// ever referenced here by path) can never be interpreted as shell syntax.
// workDir sets the transient unit's working directory (e.g. so ansible
// resolves roles/ next to the playbook); pass "" to leave it unset.
func runViaSystemdRunArgv(ctx context.Context, jobID string, argv []string, workDir string, timeoutSec, maxOutputBytes int, profile ...*SandboxProfile) JobResult {
	return runSystemdRunUnit(ctx, jobID, argv, workDir, timeoutSec, maxOutputBytes, firstProfile(profile))
}

// firstProfile returns the first non-nil profile or nil.
func firstProfile(ps []*SandboxProfile) *SandboxProfile {
	for _, p := range ps {
		if p != nil {
			return p
		}
	}
	return nil
}

// SandboxProfile carries the per-capability resource containment applied to
// transient job units (plan P4.3). Zero-value fields inherit defaults.
//
// These bound the BLAST RADIUS of a job (fork bombs, memory exhaustion,
// runaway CPU) — they are not a privilege boundary: the unit still runs as
// the agent's user. A true privilege boundary (non-root core + privileged
// broker) is Faza 2; until then profiles are the honest containment layer.
type SandboxProfile struct {
	MemoryMax        string // systemd MemoryMax, e.g. "512M" / "1G"
	TasksMax         int    // systemd TasksMax — anti fork-bomb
	CPUQuotaPercent  int    // systemd CPUQuota=NN%
	NoNewPrivileges  bool   // blocks setuid/setcap escalation inside the job
	ProtectHome      string // "" | "yes" | "read-only"
	PrivateTmp       bool   // isolated /tmp for the unit
}

// Presets shared by every executor dispatch site.
var (
	// ProfileHostMutation: package managers, service control, reboot, file
	// writes, remediation — trusted-but-constrained host operations.
	ProfileHostMutation = SandboxProfile{
		MemoryMax:       "1G",
		TasksMax:        256,
		CPUQuotaPercent: 100,
		NoNewPrivileges: true,
	}
	// ProfileArbitraryCode: EXEC_BASH / EXEC_PYTHON / ansible playbooks —
	// payloads that carry untrusted-by-design content from the control plane.
	ProfileArbitraryCode = SandboxProfile{
		MemoryMax:       "512M",
		TasksMax:        128,
		CPUQuotaPercent: 80,
		NoNewPrivileges: true,
		ProtectHome:     "read-only",
	}
)

// args returns the systemd-run -p properties for this profile.
func (p *SandboxProfile) args() []string {
	var out []string
	add := func(k, v string) { out = append(out, "-p", k+"="+v) }
	if p == nil {
		return nil
	}
	if p.MemoryMax != "" {
		add("MemoryMax", p.MemoryMax)
	}
	if p.TasksMax > 0 {
		add("TasksMax", fmt.Sprintf("%d", p.TasksMax))
	}
	if p.CPUQuotaPercent > 0 {
		add("CPUQuota", fmt.Sprintf("%d%%", p.CPUQuotaPercent))
	}
	if p.NoNewPrivileges {
		out = append(out, "-p", "NoNewPrivileges=true")
	}
	switch p.ProtectHome {
	case "yes", "read-only":
		add("ProtectHome", p.ProtectHome)
	}
	if p.PrivateTmp {
		out = append(out, "-p", "PrivateTmp=true")
	}
	return out
}

func runSystemdRunUnit(ctx context.Context, jobID string, argv []string, workDir string, timeoutSec, maxOutputBytes int, profile *SandboxProfile) JobResult {
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
	args = append(args, profile.args()...)
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
