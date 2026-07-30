package compliance

import "testing"

const sampleGetcapOutput = `/usr/bin/ping = cap_net_raw+ep
/usr/sbin/setcap = cap_setfcap+ep
`

func TestParseGetcapOutput(t *testing.T) {
	results := parseGetcapOutput(sampleGetcapOutput)
	if len(results) != 2 {
		t.Fatalf("got %d results, want 2: %v", len(results), results)
	}
	if results[0].Path != "/usr/bin/ping" || results[0].Capabilities != "cap_net_raw+ep" {
		t.Errorf("results[0] = %+v", results[0])
	}
}

func TestCapabilitiesCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*CapabilitiesCollector)(nil)
	c := NewCapabilitiesCollector()
	if c.Domain() != "capabilities" {
		t.Errorf("Domain() = %q, want capabilities", c.Domain())
	}
}
