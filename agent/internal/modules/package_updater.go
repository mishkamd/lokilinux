package modules

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// UpdatePackages installs/upgrades the given packages via the host's detected
// package manager (apt/dnf/yum/zypper). An empty or absent package_names
// param means "update everything".
func UpdatePackages(ctx context.Context, jobID string, params map[string]interface{}, timeoutSec int) JobResult {
	start := time.Now()
	fail := func(format string, a ...interface{}) JobResult {
		return JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf(format, a...), DurationMs: msSince(start)}
	}

	var names []string
	if raw, ok := params["package_names"].([]interface{}); ok {
		for _, n := range raw {
			if s, ok := n.(string); ok && s != "" {
				names = append(names, s)
			}
		}
	}

	mgr := detectPackageManager()
	command, err := packageUpdateCommand(mgr, names)
	if err != nil {
		return fail("%v", err)
	}

	if timeoutSec > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, time.Duration(timeoutSec)*time.Second)
		defer cancel()
	}

	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", command)
	out, runErr := cmd.CombinedOutput()

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
		Stdout:     truncateOutput(string(out), 4*1024*1024),
		DurationMs: msSince(start),
		Error:      errMsg,
	}
}

// packageUpdateCommand builds the shell command for the detected package
// manager. names empty means "update all installed packages".
func packageUpdateCommand(mgr string, names []string) (string, error) {
	switch mgr {
	case "apt":
		if len(names) == 0 {
			return "apt-get update && apt-get upgrade -y", nil
		}
		return "apt-get update && apt-get install --only-upgrade -y " + strings.Join(names, " "), nil
	case "dnf", "yum":
		if len(names) == 0 {
			return mgr + " upgrade -y", nil
		}
		return mgr + " upgrade -y " + strings.Join(names, " "), nil
	case "zypper":
		if len(names) == 0 {
			return "zypper update -y", nil
		}
		return "zypper update -y " + strings.Join(names, " "), nil
	default:
		return "", fmt.Errorf("unsupported package manager: %s", mgr)
	}
}
