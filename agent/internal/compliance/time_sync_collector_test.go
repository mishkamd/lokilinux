package compliance

import "testing"

func TestTimeSyncCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*TimeSyncCollector)(nil)
	c := NewTimeSyncCollector()
	if c.Domain() != "time_sync" {
		t.Errorf("Domain() = %q, want time_sync", c.Domain())
	}
}
