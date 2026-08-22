package modules

import (
	"os"
	"os/user"
	"path/filepath"
	"testing"
)

func TestIsValidOwnerName(t *testing.T) {
	valid := []string{"root", "www-data", "nginx.service", "user_1"}
	invalid := []string{"", "root; rm -rf /", "a b", "$(whoami)"}
	for _, n := range valid {
		if !isValidOwnerName(n) {
			t.Errorf("expected %q to be a valid owner/group name", n)
		}
	}
	for _, n := range invalid {
		if isValidOwnerName(n) {
			t.Errorf("expected %q to be rejected as an owner/group name", n)
		}
	}
}

func TestModeMatches(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "f")
	if err := os.WriteFile(path, []byte("x"), 0644); err != nil {
		t.Fatal(err)
	}

	if !modeMatches(path, "0644") {
		t.Errorf("expected mode 0644 to match a file just created with 0644")
	}
	if modeMatches(path, "0600") {
		t.Errorf("expected mode 0600 not to match a 0644 file")
	}
	if modeMatches(filepath.Join(dir, "missing"), "0644") {
		t.Errorf("expected modeMatches to be false for a nonexistent path")
	}
	if modeMatches(path, "not-octal") {
		t.Errorf("expected modeMatches to be false for an unparseable mode")
	}
}

func TestOwnerMatchesCurrentUser(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "f")
	if err := os.WriteFile(path, []byte("x"), 0644); err != nil {
		t.Fatal(err)
	}

	me, err := user.Current()
	if err != nil {
		t.Skip("no current user info available in this environment")
	}
	if !ownerMatches(path, me.Username, "") {
		t.Errorf("expected ownerMatches to be true for the file's actual owner")
	}
	if ownerMatches(path, "definitely-not-a-real-user-xyz", "") {
		t.Errorf("expected ownerMatches to be false for a nonexistent owner")
	}
	if ownerMatches(filepath.Join(dir, "missing"), me.Username, "") {
		t.Errorf("expected ownerMatches to be false for a nonexistent path")
	}
}
