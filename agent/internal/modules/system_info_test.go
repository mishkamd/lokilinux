package modules

import "testing"

// Regression test: fqdn() must never return an empty string — the backend
// only persists non-empty values from heartbeat (see agent_service.py
// _SYSTEM_STATUS_FIELDS guard), so an empty FQDN here would leave the
// server's Overview tab showing "—" forever.
func TestFQDN_NeverEmpty(t *testing.T) {
	result := fqdn("fallback-host")
	if result == "" {
		t.Fatal("fqdn() returned empty string, want either a resolved FQDN or the hostname fallback")
	}
}

func TestFQDN_FallsBackWhenUnresolvable(t *testing.T) {
	// A hostname that cannot resolve via `hostname -f` in the test sandbox
	// should still yield the fallback value itself, never empty.
	result := fqdn("definitely-not-a-real-host-xyz")
	if result == "" {
		t.Fatal("fqdn() returned empty string for an unresolvable hostname")
	}
}

func TestCollectHealth_ComputesMemoryAndDiskPercent(t *testing.T) {
	m := NewSystemInfoModule()
	info := &SystemInfo{
		CPUCount:      4,
		TotalMemoryKB: 1000,
		FreeMemoryKB:  250, // 75% used
		Disks: []DiskInfo{
			{MountPoint: "/", TotalBytes: 200, UsedBytes: 100}, // 50% used
		},
	}

	h := m.CollectHealth(info)

	if h.MemoryUsagePercent != 75 {
		t.Errorf("MemoryUsagePercent = %v, want 75", h.MemoryUsagePercent)
	}
	if h.DiskUsagePercent != 50 {
		t.Errorf("DiskUsagePercent = %v, want 50", h.DiskUsagePercent)
	}
}

func TestCollectHealth_ZeroTotalsDoNotDivideByZero(t *testing.T) {
	m := NewSystemInfoModule()
	info := &SystemInfo{CPUCount: 0}

	h := m.CollectHealth(info) // must not panic

	if h.MemoryUsagePercent != 0 || h.DiskUsagePercent != 0 {
		t.Errorf("expected zeroed health for empty info, got %+v", h)
	}
}
