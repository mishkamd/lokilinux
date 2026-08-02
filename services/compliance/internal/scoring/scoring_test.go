package scoring

import "testing"

func TestClassify_KnownDomains(t *testing.T) {
	tests := map[string]string{
		"sshd":           "security",
		"sysctl":         "configuration",
		"mounts":         "filesystem",
		"file_integrity": "filesystem",
		"kernel_modules": "kernel",
	}
	for domain, want := range tests {
		if got := Classify(domain); got != want {
			t.Errorf("Classify(%q) = %q, want %q", domain, got, want)
		}
	}
}

func TestClassify_UnknownDomainDefaultsToConfiguration(t *testing.T) {
	if got := Classify("some_future_domain"); got != "configuration" {
		t.Errorf("Classify(unknown) = %q, want configuration", got)
	}
}
