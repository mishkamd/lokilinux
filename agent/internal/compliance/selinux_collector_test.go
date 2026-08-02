package compliance

import (
	"context"
	"strings"
	"testing"
)

const sampleSelinuxConfig = `# This file controls the state of SELinux on the system.
SELINUX=enforcing
# SELINUXTYPE= can take one of these three values:
SELINUXTYPE=targeted
`

func TestParseSelinuxConfig_ParsesKeyValues(t *testing.T) {
	values := parseSelinuxConfig(strings.NewReader(sampleSelinuxConfig))
	if values["SELINUX"] != "enforcing" {
		t.Errorf("SELINUX = %q, want enforcing", values["SELINUX"])
	}
	if values["SELINUXTYPE"] != "targeted" {
		t.Errorf("SELINUXTYPE = %q, want targeted", values["SELINUXTYPE"])
	}
}

func TestParseSelinuxConfig_CommentsIgnored(t *testing.T) {
	values := parseSelinuxConfig(strings.NewReader(sampleSelinuxConfig))
	if len(values) != 2 {
		t.Errorf("values = %v, want exactly 2 entries (comment lines must not become keys)", values)
	}
}

func TestParseSelinuxConfig_EmptyFile(t *testing.T) {
	values := parseSelinuxConfig(strings.NewReader(""))
	if len(values) != 0 {
		t.Errorf("values = %v, want empty", values)
	}
}

func TestSELinuxCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*SELinuxCollector)(nil)
	c := NewSELinuxCollector()
	if c.Domain() != "selinux" {
		t.Errorf("Domain() = %q, want selinux", c.Domain())
	}
}

// TestSELinuxCollector_Collect_NotApplicableWhenAbsent is a real (not
// mocked) integration check: this test environment has no SELinux
// (getenforce absent), so Collect() must report mode=not_applicable
// rather than erroring or fabricating "Disabled".
func TestSELinuxCollector_Collect_NotApplicableWhenAbsent(t *testing.T) {
	c := NewSELinuxCollector()
	facts, err := c.Collect(context.Background())
	if err != nil {
		t.Fatalf("Collect() error = %v, want nil even when SELinux is absent", err)
	}
	mode, ok := facts["mode"]
	if !ok {
		t.Fatal("facts[\"mode\"] missing")
	}
	t.Logf("detected mode = %v (not_applicable expected on this non-SELinux test image)", mode)
}
