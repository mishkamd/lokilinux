package modules

import (
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"time"
)

// serviceNameRe bounds unit names to systemd's own valid charset
// (alnum, @:._- ) before they ever reach exec — same defense-in-depth
// posture as packageNameRe.
var serviceNameRe = regexp.MustCompile(`^[A-Za-z0-9@._-]+$`)

func isValidServiceName(s string) bool {
	return s != "" && serviceNameRe.MatchString(s)
}

var serviceActions = map[string]string{
	"start": "running", "stop": "stopped",
	"restart": "restarted", "reload": "reloaded",
	"enable": "enabled", "disable": "disabled",
}

// serviceAlreadySatisfied reports whether the unit is already in the state
// `action` would produce, so a retried/idempotent workflow step (e.g. after
// a partial failure) doesn't restart something already running. Read-only
// systemctl queries run directly — ProtectSystem=strict blocks the agent's
// own writes, not reads, so no systemd-run escape is needed here (compare
// the mutating path below, which does need it). restart/reload have no
// idempotent short-circuit — systemctl restart is itself safe to re-run,
// and "already restarted" isn't a real state to detect.
func serviceAlreadySatisfied(ctx context.Context, action, name string) bool {
	switch action {
	case "start":
		return exec.CommandContext(ctx, "systemctl", "is-active", "--quiet", name).Run() == nil
	case "stop":
		return exec.CommandContext(ctx, "systemctl", "is-active", "--quiet", name).Run() != nil
	case "enable":
		return exec.CommandContext(ctx, "systemctl", "is-enabled", "--quiet", name).Run() == nil
	case "disable":
		return exec.CommandContext(ctx, "systemctl", "is-enabled", "--quiet", name).Run() != nil
	default:
		return false
	}
}

// Service runs systemctl start/stop/restart/reload/enable/disable against a
// single unit, idempotently. Native form of the backend compile-down path's
// `service(action, name)` — see reboot.go's docstring on why this isn't yet
// the default dispatch path.
func Service(ctx context.Context, jobID string, params map[string]interface{}, timeoutSec int) JobResult {
	start := time.Now()
	action, _ := params["action"].(string)
	name, _ := params["name"].(string)

	stateLabel, ok := serviceActions[action]
	if !ok {
		return JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf("unsupported service action: %q", action), DurationMs: msSince(start)}
	}
	if !isValidServiceName(name) {
		return JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf("invalid service name: %q", name), DurationMs: msSince(start)}
	}

	if serviceAlreadySatisfied(ctx, action, name) {
		return JobResult{JobID: jobID, ExitCode: 0, Stdout: fmt.Sprintf("%s already %s — no-op", name, stateLabel), DurationMs: msSince(start)}
	}

	argv := []string{"systemctl", action, name}
	return runViaSystemdRunArgv(ctx, jobID, argv, "", timeoutSec, 64*1024)
}
