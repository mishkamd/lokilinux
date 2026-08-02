package compliance

import (
	"bufio"
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// SysctlCollector reads live kernel parameters via `sysctl -a` rather than
// /etc/sysctl.d/*.conf — a rule checking e.g. net.ipv4.ip_forward needs the
// value actually in effect, which can differ from what's on disk if an
// admin ran `sysctl -w` directly or a config file was edited without
// reloading.
type SysctlCollector struct{}

func NewSysctlCollector() *SysctlCollector { return &SysctlCollector{} }

func (c *SysctlCollector) Domain() string { return "sysctl" }

func (c *SysctlCollector) Interval() time.Duration { return 0 }

func (c *SysctlCollector) Collect(ctx context.Context) (Facts, error) {
	out, err := exec.CommandContext(ctx, "sysctl", "-a").Output()
	if err != nil {
		return nil, fmt.Errorf("running sysctl -a: %w", err)
	}
	return parseSysctlOutput(string(out)), nil
}

// parseSysctlOutput is a pure function so it's testable without a real
// kernel/sysctl binary. `sysctl -a` emits "key = value" per line; a handful
// of keys (e.g. kernel.sched_domain internals) can legitimately produce
// multiple space-separated numbers as the value — those are kept as the
// full trailing string, not split further, since rules compare against the
// whole value CEL-side (facts.sysctl["key"] == "expected").
func parseSysctlOutput(output string) Facts {
	facts := Facts{}
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := scanner.Text()
		idx := strings.Index(line, "=")
		if idx == -1 {
			continue // malformed/warning line (e.g. permission-denied notices sysctl -a prints to stdout on some systems)
		}
		key := strings.TrimSpace(line[:idx])
		value := strings.TrimSpace(line[idx+1:])
		if key == "" {
			continue
		}
		facts[key] = value
	}
	return facts
}
