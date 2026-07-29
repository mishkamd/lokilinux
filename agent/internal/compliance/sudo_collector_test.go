package compliance

import (
	"strings"
	"testing"
)

const sampleSudoers = `# sudoers file
Defaults env_reset

root ALL=(ALL:ALL) ALL

%wheel ALL=(ALL) NOPASSWD: ALL
`

func TestParseSudoersFile_StripsCommentsAndBlankLines(t *testing.T) {
	lines := parseSudoersFile(strings.NewReader(sampleSudoers))
	if len(lines) != 3 {
		t.Fatalf("lines = %v, want 3 (comments/blanks stripped)", lines)
	}
	if lines[0] != "Defaults env_reset" {
		t.Errorf("lines[0] = %q, want %q", lines[0], "Defaults env_reset")
	}
}

// TestParseSudoersFile_NopasswdDetectable locks the exact honest-simplification
// use case documented on SudoCollector: a CEL rule can string-match for
// "NOPASSWD: ALL" without this collector needing a real sudoers grammar.
func TestParseSudoersFile_NopasswdDetectable(t *testing.T) {
	lines := parseSudoersFile(strings.NewReader(sampleSudoers))
	found := false
	for _, l := range lines {
		if strings.Contains(l, "NOPASSWD: ALL") {
			found = true
		}
	}
	if !found {
		t.Errorf("lines = %v, want a NOPASSWD: ALL line detectable", lines)
	}
}

func TestParseSudoersFile_EmptyFile(t *testing.T) {
	lines := parseSudoersFile(strings.NewReader(""))
	if len(lines) != 0 {
		t.Errorf("lines = %v, want empty", lines)
	}
}

func TestSudoCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*SudoCollector)(nil)
	c := NewSudoCollector()
	if c.Domain() != "sudo" {
		t.Errorf("Domain() = %q, want sudo", c.Domain())
	}
}
