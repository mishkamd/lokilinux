package modules

import (
	"os"
	"strings"
	"testing"
)

func TestSandboxProfileArgs(t *testing.T) {
	p := SandboxProfile{MemoryMax: "512M", TasksMax: 128, CPUQuotaPercent: 80, NoNewPrivileges: true, ProtectHome: "read-only"}
	got := strings.Join(p.args(), " ")
	for _, want := range []string{
		"-p MemoryMax=512M",
		"-p TasksMax=128",
		"-p CPUQuota=80%",
		"-p NoNewPrivileges=true",
		"-p ProtectHome=read-only",
	} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %q in %q", want, got)
		}
	}
	if nilp := (*SandboxProfile)(nil); len(nilp.args()) != 0 {
		t.Fatal("nil profile must contribute no properties")
	}
}

func TestSandboxProfileArgs_EnvAllowlist(t *testing.T) {
	t.Setenv("PATH", "/usr/bin:/bin")
	t.Setenv("LOKI_TEST_NOT_ALLOWED", "leak-me")

	p := SandboxProfile{EnvAllowlist: []string{"PATH", "LANG", "HOME"}}
	got := strings.Join(p.args(), " ")

	if !strings.Contains(got, "-p Environment=PATH=/usr/bin:/bin") {
		t.Fatalf("allowlisted PATH missing from args: %q", got)
	}
	if strings.Contains(got, "LOKI_TEST_NOT_ALLOWED") {
		t.Fatalf("non-allowlisted env var leaked into args: %q", got)
	}
	// LANG/HOME may be unset in the test environment — only asserting they
	// never appear when genuinely absent (os.LookupEnv guards that).
	if v, ok := os.LookupEnv("LANG"); ok && !strings.Contains(got, "-p Environment=LANG="+v) {
		t.Fatalf("LANG is set but missing from args: %q", got)
	}
}

func TestPresetsContainResourceBounds(t *testing.T) {
	for name, p := range map[string]SandboxProfile{"mutation": ProfileHostMutation, "code": ProfileArbitraryCode} {
		if p.MemoryMax == "" || p.TasksMax <= 0 || p.CPUQuotaPercent <= 0 || !p.NoNewPrivileges {
			t.Fatalf("%s preset missing bounds: %+v", name, p)
		}
	}
	if ProfileArbitraryCode.ProtectHome != "read-only" {
		t.Fatal("arbitrary-code jobs must shield /home")
	}
}
