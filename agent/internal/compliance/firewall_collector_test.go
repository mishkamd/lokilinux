package compliance

import (
	"context"
	"os"
	"path/filepath"
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

// TestFirewallCollector_Collect_NoBinariesReportsNotApplicable covers the
// "no firewall binary present" path. It must be hermetic: the original
// version probed the real host paths, which passes only on a build machine
// without firewall tooling — a host that has /usr/sbin/nft or iptables-save
// (where Collect runs the real command and errors as a non-root user) made
// the test fail even though the product code is correct. Override the
// backend list with guaranteed-absent paths to exercise the exact
// not_applicable fallback regardless of the build host.
func TestFirewallCollector_Collect_NoBinariesReportsNotApplicable(t *testing.T) {
	orig := firewallBackends
	firewallBackends = []struct {
		binaryPath string
		name       string
		args       []string
	}{
		{t.TempDir() + "/absent-firewall-cmd", "firewalld", nil},
		{t.TempDir() + "/absent-nft", "nftables", nil},
		{t.TempDir() + "/absent-iptables-save", "iptables", nil},
	}
	t.Cleanup(func() { firewallBackends = orig })

	c := NewFirewallCollector()
	facts, err := c.Collect(context.Background())
	if err != nil {
		t.Fatalf("Collect() error = %v, want nil", err)
	}
	if facts["backend"] != "not_applicable" {
		t.Fatalf("facts[\"backend\"] = %v, want not_applicable", facts["backend"])
	}
}

// TestFirewallCollector_Collect_BinaryPresentButErrorsDegradesInsteadOfFailing
// covers a firewall binary that exists but errors when run (permission
// denied, DBus unavailable, missing CAP_NET_ADMIN in a netns, ...). Collect
// must report a degraded fact for the domain, not an error — an error here
// makes the runner skip updating domain_hashes/domain_full, silently
// dropping "firewall" from every heartbeat instead of degrading like every
// sibling collector (auditd, container runtime).
func TestFirewallCollector_Collect_BinaryPresentButErrorsDegradesInsteadOfFailing(t *testing.T) {
	dir := t.TempDir()
	failing := filepath.Join(dir, "failing-nft")
	if err := os.WriteFile(failing, []byte("#!/bin/sh\nexit 1\n"), 0o755); err != nil {
		t.Fatal(err)
	}

	orig := firewallBackends
	firewallBackends = []struct {
		binaryPath string
		name       string
		args       []string
	}{
		{failing, "nftables", nil},
	}
	t.Cleanup(func() { firewallBackends = orig })

	c := NewFirewallCollector()
	facts, err := c.Collect(context.Background())
	if err != nil {
		t.Fatalf("Collect() error = %v, want nil (degraded fact instead)", err)
	}
	if facts["backend"] != "nftables" {
		t.Errorf("facts[\"backend\"] = %v, want nftables", facts["backend"])
	}
	if facts["error"] == nil || facts["error"] == "" {
		t.Errorf("facts[\"error\"] missing/empty, want the exec error surfaced")
	}
}

func TestFirewallCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*FirewallCollector)(nil)
	c := NewFirewallCollector()
	if c.Domain() != "firewall" {
		t.Errorf("Domain() = %q, want firewall", c.Domain())
	}
}
