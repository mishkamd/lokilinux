package compliance

import (
	"strings"
	"testing"
)

const sampleResolvConf = `# comment
nameserver 1.1.1.1
nameserver 8.8.8.8
search example.com corp.internal
options timeout:2 attempts:3
`

func TestParseResolvConf(t *testing.T) {
	conf := parseResolvConf(strings.NewReader(sampleResolvConf))
	if len(conf.Nameservers) != 2 || conf.Nameservers[0] != "1.1.1.1" {
		t.Errorf("Nameservers = %v, want [1.1.1.1 8.8.8.8]", conf.Nameservers)
	}
	if len(conf.Search) != 2 {
		t.Errorf("Search = %v, want 2 entries", conf.Search)
	}
	if len(conf.Options) != 2 {
		t.Errorf("Options = %v, want 2 entries", conf.Options)
	}
}

func TestNetworkCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*NetworkCollector)(nil)
	c := NewNetworkCollector()
	if c.Domain() != "network" {
		t.Errorf("Domain() = %q, want network", c.Domain())
	}
}
