package modules

import (
	"context"
	"fmt"
	"time"
)

var systemActionUnitCmd = map[string]string{
	"reboot":   "reboot",
	"shutdown": "poweroff",
}

// Reboot schedules a deferred reboot/poweroff via `systemd-run
// --on-active=Ns systemctl <action>` — the same trick the backend's
// compile-down path already uses for `system(action=reboot|shutdown)`
// (services/workflow_engine.py's _compile_system): the scheduling command
// itself returns in milliseconds, so this job reports COMPLETED well before
// the machine actually goes down, instead of hanging until
// JobTimeoutWorker kills it an hour later. Native form of the same
// behavior, kept for Faza 10 — not yet wired as the default dispatch path
// (see manager.go's runJob switch comment).
func Reboot(ctx context.Context, jobID string, params map[string]interface{}, timeoutSec int) JobResult {
	start := time.Now()
	action, _ := params["action"].(string)
	unitCmd, ok := systemActionUnitCmd[action]
	if !ok {
		return JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf("unsupported system action: %q", action), DurationMs: msSince(start)}
	}

	delay := 5
	if d, ok := params["delay_seconds"].(float64); ok && d > 0 {
		delay = int(d)
	}

	argv := []string{"systemd-run", fmt.Sprintf("--on-active=%ds", delay), "systemctl", unitCmd}
	return runViaSystemdRunArgv(ctx, jobID, argv, "", timeoutSec, 64*1024, &ProfileHostMutation)
}
