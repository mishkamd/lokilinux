package compliance

import "testing"

// TestRegistry_AllDomainsUnique guards against two collectors accidentally
// claiming the same domain key — inventory_snapshots.domain is used as a
// dedup/lookup key everywhere downstream, so a collision would silently
// make one collector's data invisible.
func TestRegistry_AllDomainsUnique(t *testing.T) {
	seen := map[string]bool{}
	for _, c := range Registry {
		if seen[c.Domain()] {
			t.Errorf("duplicate domain %q in Registry", c.Domain())
		}
		seen[c.Domain()] = true
	}
	if len(Registry) == 0 {
		t.Fatal("Registry is empty")
	}
}

func TestRegistry_ContainsExpectedDomains(t *testing.T) {
	want := map[string]bool{
		"sshd": false, "sysctl": false, "users": false, "mounts": false,
		"sudo": false, "pam": false, "auditd": false, "firewall": false, "selinux": false,
	}
	for _, c := range Registry {
		if _, ok := want[c.Domain()]; ok {
			want[c.Domain()] = true
		}
	}
	for domain, found := range want {
		if !found {
			t.Errorf("Registry missing expected collector for domain %q", domain)
		}
	}
}
