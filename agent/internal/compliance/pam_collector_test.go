package compliance

import (
	"strings"
	"testing"
)

const samplePAMStack = `#%PAM-1.0
auth       required     pam_unix.so nullok
auth       [success=1 default=ignore] pam_unix.so
account    required     pam_unix.so
session    optional     pam_permit.so
`

func TestParsePAMStack_PlainControl(t *testing.T) {
	lines := parsePAMStack(strings.NewReader(samplePAMStack))
	if len(lines) != 4 {
		t.Fatalf("lines = %+v, want 4", lines)
	}
	if lines[0].Type != "auth" || lines[0].Control != "required" || lines[0].Module != "pam_unix.so" {
		t.Errorf("lines[0] = %+v, want auth/required/pam_unix.so", lines[0])
	}
	if len(lines[0].Args) != 1 || lines[0].Args[0] != "nullok" {
		t.Errorf("lines[0].Args = %v, want [nullok]", lines[0].Args)
	}
}

// TestParsePAMStack_BracketedControl locks that a multi-token bracketed
// control value is reassembled as one string, not split across Control/Module.
func TestParsePAMStack_BracketedControl(t *testing.T) {
	lines := parsePAMStack(strings.NewReader(samplePAMStack))
	bracketed := lines[1]
	if bracketed.Control != "[success=1 default=ignore]" {
		t.Errorf("Control = %q, want the full bracketed expression", bracketed.Control)
	}
	if bracketed.Module != "pam_unix.so" {
		t.Errorf("Module = %q, want pam_unix.so (not swallowed into Control)", bracketed.Module)
	}
}

func TestParsePAMStack_CommentsAndHeaderIgnored(t *testing.T) {
	lines := parsePAMStack(strings.NewReader("#%PAM-1.0\n# a comment\n\nauth required pam_unix.so\n"))
	if len(lines) != 1 {
		t.Errorf("lines = %+v, want exactly 1", lines)
	}
}

func TestParsePAMStack_EmptyFile(t *testing.T) {
	lines := parsePAMStack(strings.NewReader(""))
	if len(lines) != 0 {
		t.Errorf("lines = %+v, want empty", lines)
	}
}

func TestPAMCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*PAMCollector)(nil)
	c := NewPAMCollector()
	if c.Domain() != "pam" {
		t.Errorf("Domain() = %q, want pam", c.Domain())
	}
}
