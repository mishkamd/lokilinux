package compliance

import (
	"bufio"
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// SSHDCollector reads the *effective* sshd configuration via `sshd -T`
// rather than parsing /etc/ssh/sshd_config directly — the file alone
// misses Include directives, command-line overrides, and built-in
// defaults, so a rule checking PermitRootLogin against the raw file can be
// wrong even when the file looks compliant.
type SSHDCollector struct{}

func NewSSHDCollector() *SSHDCollector { return &SSHDCollector{} }

func (c *SSHDCollector) Domain() string { return "sshd" }

// Interval is 0 (every heartbeat) — sshd -T is a cheap, local process call,
// not a filesystem walk, so it doesn't need the reduced cadence expensive
// collectors get (docs/compliance/03-AGENT-PLUGIN-SDK.md §5).
func (c *SSHDCollector) Interval() time.Duration { return 0 }

func (c *SSHDCollector) Collect(ctx context.Context) (Facts, error) {
	out, err := exec.CommandContext(ctx, "sshd", "-T").Output()
	if err != nil {
		return nil, fmt.Errorf("running sshd -T: %w", err)
	}
	return parseSSHDConfig(string(out)), nil
}

// parseSSHDConfig is a pure function, split out from Collect so it can be
// unit-tested without a real sshd binary in the test environment.
//
// `sshd -T` output is one directive per line, lowercase key, space-
// separated from its value(s): "permitrootlogin no". A handful of
// directives (hostkey, acceptenv, ...) are legitimately repeated across
// multiple lines — those collect into a []string rather than overwriting.
func parseSSHDConfig(output string) Facts {
	facts := Facts{}
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		fields := strings.SplitN(line, " ", 2)
		key := fields[0]
		value := ""
		if len(fields) == 2 {
			value = strings.TrimSpace(fields[1])
		}

		existing, seen := facts[key]
		if !seen {
			facts[key] = value
			continue
		}
		switch v := existing.(type) {
		case string:
			facts[key] = []string{v, value}
		case []string:
			facts[key] = append(v, value)
		}
	}
	return facts
}
