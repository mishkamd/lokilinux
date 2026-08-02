package compliance

import "testing"

const sampleSysctlOutput = `kernel.hostname = web-01
net.ipv4.ip_forward = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.tcp_syncookies = 1
kernel.sched_domain.cpu0.domain0.max_newidle_lb_cost = 12345 67890
`

func TestParseSysctlOutput_ScalarKeys(t *testing.T) {
	facts := parseSysctlOutput(sampleSysctlOutput)

	tests := map[string]string{
		"kernel.hostname":                    "web-01",
		"net.ipv4.ip_forward":                "0",
		"net.ipv4.conf.all.accept_redirects": "0",
		"net.ipv4.tcp_syncookies":            "1",
	}
	for key, want := range tests {
		got, ok := facts[key]
		if !ok {
			t.Errorf("facts[%q] missing", key)
			continue
		}
		if got != want {
			t.Errorf("facts[%q] = %v, want %q", key, got, want)
		}
	}
}

// TestParseSysctlOutput_MultiValueKeptWhole locks that a key whose value
// contains multiple space-separated numbers isn't truncated to just the
// first token — CEL rules compare the whole trailing string.
func TestParseSysctlOutput_MultiValueKeptWhole(t *testing.T) {
	facts := parseSysctlOutput(sampleSysctlOutput)
	got, ok := facts["kernel.sched_domain.cpu0.domain0.max_newidle_lb_cost"]
	if !ok {
		t.Fatal("multi-value key missing")
	}
	if got != "12345 67890" {
		t.Errorf("got %q, want the full trailing value \"12345 67890\"", got)
	}
}

func TestParseSysctlOutput_MalformedLinesIgnored(t *testing.T) {
	facts := parseSysctlOutput("not a valid line at all\nnet.ipv4.ip_forward = 0\n")
	if len(facts) != 1 {
		t.Errorf("facts = %v, want exactly 1 entry (the malformed line must be skipped)", facts)
	}
}

func TestParseSysctlOutput_EmptyOutput(t *testing.T) {
	facts := parseSysctlOutput("")
	if len(facts) != 0 {
		t.Errorf("facts = %v, want empty", facts)
	}
}

func TestSysctlCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*SysctlCollector)(nil)
	c := NewSysctlCollector()
	if c.Domain() != "sysctl" {
		t.Errorf("Domain() = %q, want sysctl", c.Domain())
	}
}
