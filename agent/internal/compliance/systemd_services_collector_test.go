package compliance

import "testing"

const sampleUnitFiles = `sshd.service                          enabled
rescue.service                        static
cron.service                          enabled
`

func TestParseUnitFiles(t *testing.T) {
	units := parseUnitFiles(sampleUnitFiles)
	if len(units) != 3 {
		t.Fatalf("got %d units, want 3: %v", len(units), units)
	}
	if units[0].Unit != "sshd.service" || units[0].State != "enabled" {
		t.Errorf("units[0] = %+v, want {sshd.service enabled}", units[0])
	}
}

func TestSystemdServicesCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*SystemdServicesCollector)(nil)
	c := NewSystemdServicesCollector()
	if c.Domain() != "systemd_services" {
		t.Errorf("Domain() = %q, want systemd_services", c.Domain())
	}
}
