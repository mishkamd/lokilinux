package compliance

import (
	"context"
	"os"
	"os/exec"
	"strings"
	"time"
)

// FirewallCollector detects which firewall backend is active — firewalld
// (RHEL-family default), nftables, or legacy iptables (Debian-family) —
// and captures its full ruleset as text.
//
// ponytail: raw ruleset text, not a parsed rule structure — firewalld
// zones and nftables rule syntax are each their own grammar, and a CEL
// rule checking "port 22 is open" can string-match the raw dump. Upgrade
// to structured parsing per-backend if a rule needs it.
type FirewallCollector struct{}

func NewFirewallCollector() *FirewallCollector { return &FirewallCollector{} }

func (c *FirewallCollector) Domain() string { return "firewall" }

func (c *FirewallCollector) Interval() time.Duration { return 0 }

// firewallBackends is checked in order (not a map — map iteration order is
// random in Go, which would make backend selection nondeterministic on a
// host that somehow has more than one binary present).
var firewallBackends = []struct {
	binaryPath string
	name       string
	args       []string
}{
	{"/usr/bin/firewall-cmd", "firewalld", []string{"--list-all-zones"}},
	{"/usr/sbin/nft", "nftables", []string{"list", "ruleset"}},
	{"/usr/sbin/iptables-save", "iptables", nil},
}

func (c *FirewallCollector) Collect(ctx context.Context) (Facts, error) {
	for _, backend := range firewallBackends {
		if _, err := os.Stat(backend.binaryPath); err != nil {
			continue
		}
		out, err := exec.CommandContext(ctx, backend.binaryPath, backend.args...).Output()
		if err != nil {
			// Binary present but erroring (permission denied, DBus down,
			// missing CAP_NET_ADMIN in a netns, ...) is a degraded fact, not
			// a collection failure — mirrors auditd_collector.go /
			// container_runtime_collector.go. Returning an error here would
			// make the runner skip updating domain_hashes/domain_full
			// entirely, silently dropping "firewall" from every heartbeat.
			return Facts{"backend": backend.name, "error": err.Error()}, nil
		}
		return Facts{"backend": backend.name, "ruleset": strings.TrimSpace(string(out))}, nil
	}
	return Facts{"backend": "not_applicable"}, nil
}
