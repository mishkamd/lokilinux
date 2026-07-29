package drift

import "testing"

func TestDetect_NoChange_ReturnsNil(t *testing.T) {
	facts := map[string]any{"PermitRootLogin": "no"}
	e := Detect("sshd", ComparedAgainstPreviousSnapshot, facts, facts)
	if e != nil {
		t.Errorf("Detect() = %+v, want nil for identical documents", e)
	}
}

func TestDetect_ScalarFieldChanged(t *testing.T) {
	old := map[string]any{"PermitRootLogin": "no"}
	new_ := map[string]any{"PermitRootLogin": "yes"}

	e := Detect("sshd", ComparedAgainstPreviousSnapshot, old, new_)
	if e == nil {
		t.Fatal("Detect() = nil, want an event for a changed field")
	}
	if len(e.FieldDiffs) != 1 {
		t.Fatalf("FieldDiffs = %v, want 1 entry", e.FieldDiffs)
	}
	if e.FieldDiffs[0].FieldPath != "/PermitRootLogin" {
		t.Errorf("FieldPath = %q, want /PermitRootLogin", e.FieldDiffs[0].FieldPath)
	}
	if e.FieldDiffs[0].OldValue != "no" || e.FieldDiffs[0].NewValue != "yes" {
		t.Errorf("OldValue/NewValue = %v/%v, want no/yes", e.FieldDiffs[0].OldValue, e.FieldDiffs[0].NewValue)
	}
}

func TestDetect_FieldAdded(t *testing.T) {
	old := map[string]any{"PermitRootLogin": "no"}
	new_ := map[string]any{"PermitRootLogin": "no", "X11Forwarding": "yes"}

	e := Detect("sshd", ComparedAgainstPreviousSnapshot, old, new_)
	if e == nil {
		t.Fatal("Detect() = nil, want an event for an added field")
	}
	if e.FieldDiffs[0].OldValue != nil {
		t.Errorf("OldValue = %v, want nil for a newly-added field", e.FieldDiffs[0].OldValue)
	}
	if e.FieldDiffs[0].NewValue != "yes" {
		t.Errorf("NewValue = %v, want yes", e.FieldDiffs[0].NewValue)
	}
}

func TestDetect_FieldRemoved(t *testing.T) {
	old := map[string]any{"PermitRootLogin": "no", "X11Forwarding": "yes"}
	new_ := map[string]any{"PermitRootLogin": "no"}

	e := Detect("sshd", ComparedAgainstPreviousSnapshot, old, new_)
	if e == nil {
		t.Fatal("Detect() = nil, want an event for a removed field")
	}
	if e.FieldDiffs[0].NewValue != nil {
		t.Errorf("NewValue = %v, want nil for a removed field", e.FieldDiffs[0].NewValue)
	}
}

// TestDetect_NestedFieldChanged locks that a diff inside a nested map
// (e.g. mounts.options-shaped structures once those collectors exist)
// produces a slash-joined JSON-pointer path, not a flat top-level one.
func TestDetect_NestedFieldChanged(t *testing.T) {
	old := map[string]any{"sysctl": map[string]any{"net.ipv4.ip_forward": "0"}}
	new_ := map[string]any{"sysctl": map[string]any{"net.ipv4.ip_forward": "1"}}

	e := Detect("sysctl", ComparedAgainstPreviousSnapshot, old, new_)
	if e == nil {
		t.Fatal("Detect() = nil, want an event")
	}
	if e.FieldDiffs[0].FieldPath != "/sysctl/net.ipv4.ip_forward" {
		t.Errorf("FieldPath = %q, want /sysctl/net.ipv4.ip_forward", e.FieldDiffs[0].FieldPath)
	}
}

func TestDetect_MultipleFieldsChanged_SortedDeterministically(t *testing.T) {
	old := map[string]any{"a": "1", "z": "1", "m": "1"}
	new_ := map[string]any{"a": "2", "z": "2", "m": "2"}

	e := Detect("test", ComparedAgainstPreviousSnapshot, old, new_)
	if len(e.FieldDiffs) != 3 {
		t.Fatalf("FieldDiffs len = %d, want 3", len(e.FieldDiffs))
	}
	paths := []string{e.FieldDiffs[0].FieldPath, e.FieldDiffs[1].FieldPath, e.FieldDiffs[2].FieldPath}
	if paths[0] != "/a" || paths[1] != "/m" || paths[2] != "/z" {
		t.Errorf("FieldDiffs order = %v, want alphabetically sorted paths", paths)
	}
}

func TestClassifySeverity_KnownDomains(t *testing.T) {
	tests := map[string]Severity{
		"selinux": SeverityCritical,
		"sudo":    SeverityCritical,
		"users":   SeverityHigh,
		"sshd":    SeverityHigh,
		"sysctl":  SeverityMedium,
		"mounts":  SeverityLow,
	}
	for domain, want := range tests {
		if got := ClassifySeverity(domain); got != want {
			t.Errorf("ClassifySeverity(%q) = %v, want %v", domain, got, want)
		}
	}
}

func TestClassifySeverity_UnknownDomainDefaultsToMedium(t *testing.T) {
	if got := ClassifySeverity("some_future_domain_nobody_classified_yet"); got != SeverityMedium {
		t.Errorf("ClassifySeverity(unknown) = %v, want MEDIUM (never silently LOW)", got)
	}
}

func TestDetect_EmptyToPopulated_TreatedAsAllFieldsAdded(t *testing.T) {
	e := Detect("sshd", ComparedAgainstPreviousSnapshot, map[string]any{}, map[string]any{"PermitRootLogin": "no"})
	if e == nil {
		t.Fatal("Detect() = nil, want an event when a domain goes from empty to populated")
	}
	if len(e.FieldDiffs) != 1 {
		t.Errorf("FieldDiffs = %v, want 1", e.FieldDiffs)
	}
}
