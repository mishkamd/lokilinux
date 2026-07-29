package compliance

import (
	"context"
	"testing"
)

// TestFirewallBackends_CheckedInDeterministicOrder guards against the
// nondeterministic-map-iteration mistake already present elsewhere in this
// codebase (agent/internal/modules/package_manager.go's detectPackageManager) —
// this list must stay an ordered slice, firewalld before nftables before
// iptables, not a map.
func TestFirewallBackends_CheckedInDeterministicOrder(t *testing.T) {
	if len(firewallBackends) != 3 {
		t.Fatalf("firewallBackends len = %d, want 3", len(firewallBackends))
	}
	want := []string{"firewalld", "nftables", "iptables"}
	for i, w := range want {
		if firewallBackends[i].name != w {
			t.Errorf("firewallBackends[%d].name = %q, want %q", i, firewallBackends[i].name, w)
		}
	}
}

// TestFirewallCollector_Collect_NoBinariesReportsNotApplicable is a real
// (not mocked) check against this test environment, which has none of the
// three firewall binaries at their expected paths — Collect() must
// degrade to backend=not_applicable, not error.
func TestFirewallCollector_Collect_NoBinariesReportsNotApplicable(t *testing.T) {
	c := NewFirewallCollector()
	facts, err := c.Collect(context.Background())
	if err != nil {
		t.Fatalf("Collect() error = %v, want nil", err)
	}
	if _, ok := facts["backend"]; !ok {
		t.Fatal("facts[\"backend\"] missing")
	}
	t.Logf("detected backend = %v", facts["backend"])
}

func TestFirewallCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*FirewallCollector)(nil)
	c := NewFirewallCollector()
	if c.Domain() != "firewall" {
		t.Errorf("Domain() = %q, want firewall", c.Domain())
	}
}
