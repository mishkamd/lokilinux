package modules

import (
	"context"
	"fmt"
	"regexp"
	"time"
)

// packageNameRe bounds package_names to the charset real package names use
// (Debian/RPM naming conventions) before they ever reach exec — defense in
// depth on top of packageUpdateArgv never invoking a shell over them.
var packageNameRe = regexp.MustCompile(`^[A-Za-z0-9+._:-]+$`)

// isValidPackageName rejects anything packageNameRe wouldn't match, plus a
// leading hyphen: dnf/yum/zypper receive names without a "--" separator (see
// packageUpdateArgv), so a value like "--installroot=/tmp/evil" would be
// parsed as an option, not a package name, even though the charset alone
// allows it.
func isValidPackageName(s string) bool {
	return s != "" && s[0] != '-' && packageNameRe.MatchString(s)
}

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
				if !isValidPackageName(s) {
					return fail("invalid package name: %q", s)
				}
				names = append(names, s)
			}
		}
	}

	mgr := detectPackageManager()
	argv, err := packageUpdateArgv(mgr, names)
	if err != nil {
		return fail("%v", err)
	}

	// Escapes the agent's own sandbox (ProtectSystem=strict) — see
	// systemd_run.go. Installing packages means writing into /usr, which
	// the agent's own mount namespace can never do regardless of
	// ReadWritePaths.
	return runViaSystemdRunArgv(ctx, jobID, argv, "", timeoutSec, 4*1024*1024, &ProfileHostMutation)
}

// packageUpdateArgv builds the argv for the detected package manager — never
// a shell string — so package_names (job-parameter, untrusted) can't be
// interpreted as shell syntax. names empty means "update all installed
// packages". apt is the one manager that needs two chained commands
// (update, then install); package_names there are passed after `--` and
// referenced via "$@", so the shell only ever expands them as literal
// positional arguments, never as syntax.
func packageUpdateArgv(mgr string, names []string) ([]string, error) {
	switch mgr {
	case "apt":
		if len(names) == 0 {
			return []string{"/bin/sh", "-c", "apt-get update && apt-get upgrade -y"}, nil
		}
		argv := []string{"/bin/sh", "-c", `apt-get update && apt-get install --only-upgrade -y "$@"`, "--"}
		return append(argv, names...), nil
	case "dnf", "yum":
		if len(names) == 0 {
			return []string{mgr, "upgrade", "-y"}, nil
		}
		return append([]string{mgr, "upgrade", "-y"}, names...), nil
	case "zypper":
		if len(names) == 0 {
			return []string{"zypper", "update", "-y"}, nil
		}
		return append([]string{"zypper", "update", "-y"}, names...), nil
	default:
		return nil, fmt.Errorf("unsupported package manager: %s", mgr)
	}
}
