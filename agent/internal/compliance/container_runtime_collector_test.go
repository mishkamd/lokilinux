package compliance

import (
	"context"
	"testing"
)

func TestContainerRuntimeCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*ContainerRuntimeCollector)(nil)
	c := NewContainerRuntimeCollector()
	if c.Domain() != "container_runtime" {
		t.Errorf("Domain() = %q, want container_runtime", c.Domain())
	}
}

func TestContainerRuntimeCollector_Collect_NeverErrors(t *testing.T) {
	// Whether or not docker/podman/kubectl are present on the test runner,
	// Collect must succeed — absence is a normal state, not a failure.
	c := NewContainerRuntimeCollector()
	facts, err := c.Collect(context.Background())
	if err != nil {
		t.Fatalf("Collect returned error: %v", err)
	}
	if facts == nil {
		t.Fatal("Collect returned nil Facts")
	}
}
