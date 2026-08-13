package scope

import "testing"

func TestPlatformID_DistroPlusMajorVersion(t *testing.T) {
	cases := []struct {
		distro, version, want string
	}{
		{"rocky", "9.8", "rocky9"},
		{"ol", "9.2", "ol9"},
		{"rhel", "9.4", "rhel9"},
		{"ubuntu", "22.04", "ubuntu22"},
		{"RHEL", "9", "rhel9"}, // no dot at all — still works
	}
	for _, tc := range cases {
		if got := PlatformID(tc.distro, tc.version); got != tc.want {
			t.Errorf("PlatformID(%q, %q) = %q, want %q", tc.distro, tc.version, got, tc.want)
		}
	}
}

func TestPlatformID_EmptyInputsReturnEmpty(t *testing.T) {
	if got := PlatformID("", "9"); got != "" {
		t.Errorf("PlatformID(empty distro) = %q, want empty", got)
	}
	if got := PlatformID("rocky", ""); got != "" {
		t.Errorf("PlatformID(empty version) = %q, want empty", got)
	}
}

func TestPlatformApplicable_EmptyFilterMatchesEverything(t *testing.T) {
	if !PlatformApplicable(nil, "rocky9") {
		t.Error("nil platform_filter must apply to every platform")
	}
	if !PlatformApplicable([]string{}, "") {
		t.Error("empty platform_filter must apply even to an unknown platform")
	}
}

func TestPlatformApplicable_MatchIsCaseInsensitive(t *testing.T) {
	if !PlatformApplicable([]string{"Rocky9", "RHEL9"}, "rocky9") {
		t.Error("platform match must be case-insensitive")
	}
}

func TestPlatformApplicable_NoMatch(t *testing.T) {
	if PlatformApplicable([]string{"rhel9"}, "ubuntu22") {
		t.Error("ubuntu22 must not match a rhel9-only filter")
	}
}

func TestPlatformApplicable_UnknownAgentPlatformNeverApplicable(t *testing.T) {
	if PlatformApplicable([]string{"rhel9"}, "") {
		t.Error("an agent with no known platform must never be claimed applicable to a scoped rule")
	}
}
