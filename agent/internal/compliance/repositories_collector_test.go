package compliance

import (
	"os"
	"path/filepath"
	"testing"
)

func TestReadReposByGlob(t *testing.T) {
	dir := t.TempDir()
	content := "# comment\n[example]\nname=Example\nbaseurl=https://example.com\n"
	if err := os.WriteFile(filepath.Join(dir, "example.repo"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	repos := readReposByGlob(filepath.Join(dir, "*.repo"))
	if len(repos) != 1 {
		t.Fatalf("got %d repo files, want 1: %v", len(repos), repos)
	}
	lines, ok := repos["example.repo"]
	if !ok {
		t.Fatal("example.repo missing from result")
	}
	if len(lines) != 3 {
		t.Errorf("got %d lines, want 3 (comment stripped): %v", len(lines), lines)
	}
}

func TestRepositoriesCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*RepositoriesCollector)(nil)
	c := NewRepositoriesCollector()
	if c.Domain() != "repositories" {
		t.Errorf("Domain() = %q, want repositories", c.Domain())
	}
}
