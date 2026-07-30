package compliance

import (
	"context"
	"testing"
)

func TestOpenPortsCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*OpenPortsCollector)(nil)
	c := NewOpenPortsCollector()
	if c.Domain() != "open_ports" {
		t.Errorf("Domain() = %q, want open_ports", c.Domain())
	}
}

func TestOpenPortsCollector_Collect_NeverErrors(t *testing.T) {
	c := NewOpenPortsCollector()
	facts, err := c.Collect(context.Background())
	if err != nil {
		t.Fatalf("Collect returned error: %v", err)
	}
	if _, ok := facts["listening_ports"]; !ok {
		t.Error("facts missing listening_ports key")
	}
}
