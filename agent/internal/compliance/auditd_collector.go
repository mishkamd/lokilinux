package compliance

import (
	"bufio"
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"
)

// AuditdCollector reads the *active* audit rule set via `auditctl -l`
// rather than parsing /etc/audit/rules.d/*.rules directly — rules on disk
// only take effect after `augenrules --load` (or a service restart), so the
// file and the running kernel state can legitimately disagree.
//
// ponytail: raw rule-line strings, not a parsed field-by-field structure —
// auditctl's rule syntax (multiple flag forms, field comparators, syscall
// lists) is its own grammar; CEL string-matching against the raw line
// covers the common "does this exact rule exist" check. Upgrade to a real
// parser if a rule needs structural matching (e.g. "any rule watching
// /etc/shadow regardless of flag order").
type AuditdCollector struct{}

func NewAuditdCollector() *AuditdCollector { return &AuditdCollector{} }

func (c *AuditdCollector) Domain() string { return "auditd" }

func (c *AuditdCollector) Interval() time.Duration { return 0 }

func (c *AuditdCollector) Collect(ctx context.Context) (Facts, error) {
	out, err := exec.CommandContext(ctx, "auditctl", "-l").Output()
	if err != nil {
		var exitErr *exec.Error
		if errors.As(err, &exitErr) {
			// auditd not installed (common on Debian-family hosts, per
			// docs/compliance/03-AGENT-PLUGIN-SDK.md's per-distro table) —
			// an honest gap, not a collection failure.
			return Facts{"rules": []string{}, "installed": false}, nil
		}
		return nil, err
	}
	return Facts{"rules": parseAuditctlOutput(string(out)), "installed": true}, nil
}

// parseAuditctlOutput splits auditctl -l output into rule lines. Lines like
// "No rules" or "-a never,task" are kept as-is (not special-cased away) —
// they're real, meaningful auditctl output. Only blank lines are dropped.
func parseAuditctlOutput(output string) []string {
	var rules []string
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		rules = append(rules, line)
	}
	return rules
}
