package compliance

import (
	"context"
	"os/exec"
	"strings"
	"time"
)

// ContainerRuntimeCollector reports which container runtime is present —
// docker, podman, or a Kubernetes client — running each binary's own
// version/info command only if it's found on PATH. Absence of all three
// is a normal, expected state on plain package-management-only servers,
// never treated as an error.
type ContainerRuntimeCollector struct{}

func NewContainerRuntimeCollector() *ContainerRuntimeCollector { return &ContainerRuntimeCollector{} }

func (c *ContainerRuntimeCollector) Domain() string { return "container_runtime" }

func (c *ContainerRuntimeCollector) Interval() time.Duration { return 0 }

var containerRuntimeChecks = []struct {
	key  string
	bin  string
	args []string
}{
	{"docker", "docker", []string{"info", "--format", "{{.ServerVersion}}"}},
	{"podman", "podman", []string{"info", "--format", "{{.Version.Version}}"}},
	{"kubectl", "kubectl", []string{"version", "--client", "--output=yaml"}},
}

func (c *ContainerRuntimeCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}
	for _, check := range containerRuntimeChecks {
		if _, err := exec.LookPath(check.bin); err != nil {
			continue // not installed — not_applicable, never fabricated
		}
		out, err := exec.CommandContext(ctx, check.bin, check.args...).Output()
		if err != nil {
			facts[check.key] = "present_but_errored"
			continue
		}
		facts[check.key] = strings.TrimSpace(string(out))
	}
	if len(facts) == 0 {
		facts["runtime"] = "not_applicable"
	}
	return facts, nil
}
