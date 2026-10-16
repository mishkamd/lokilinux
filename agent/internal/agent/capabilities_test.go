package agent

import "testing"

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
