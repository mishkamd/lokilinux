package agent

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNativeCapabilitiesAreUniqueAndIncludeTheModules(t *testing.T) {
	seen := make(map[string]bool)
	for _, c := range nativeCapabilities() {
		if seen[c] {
			t.Fatalf("duplicate capability %q", c)
		}
		seen[c] = true
	}
	for _, want := range []string{"SERVICE", "FILE", "REBOOT", "WORKFLOW_STEPS", "PACKAGE_UPDATE"} {
		if !seen[want] {
			t.Fatalf("capability %q missing", want)
		}
	}
}

func TestNativeCapabilitiesReportAnsibleOnlyWhenTheBinaryIsThere(t *testing.T) {
	// The control plane picks runners from this list, so advertising
	// ANSIBLE_PLAYBOOK on a host without ansible-core sends the operator
	// into a job that fails at exec time.
	dir := t.TempDir()
	t.Setenv("PATH", dir)

	if hasCapability(nativeCapabilities(), "ANSIBLE_PLAYBOOK") {
		t.Fatal("agent without ansible-playbook must not advertise ANSIBLE_PLAYBOOK")
	}

	stub := filepath.Join(dir, "ansible-playbook")
	if err := os.WriteFile(stub, []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
		t.Fatalf("write stub: %v", err)
	}
	if !hasCapability(nativeCapabilities(), "ANSIBLE_PLAYBOOK") {
		t.Fatal("agent with ansible-playbook must advertise ANSIBLE_PLAYBOOK")
	}
}

func hasCapability(caps []string, want string) bool {
	for _, c := range caps {
		if c == want {
			return true
		}
	}
	return false
}
