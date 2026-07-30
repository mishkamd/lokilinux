package compliance

import (
	"os"
	"path/filepath"
	"testing"
)

func TestIsIgnoredPath_GlobAndPrefix(t *testing.T) {
	ignores := []string{"/etc/*.bak", "/etc/noisy-dir"}
	tests := map[string]bool{
		"/etc/passwd.bak":            true,
		"/etc/noisy-dir/sub/file":    true,
		"/etc/noisy-dir":             true,
		"/etc/passwd":                false,
		"/etc/noisy-dir-unrelated/x": false,
	}
	for path, want := range tests {
		if got := isIgnoredPath(path, ignores); got != want {
			t.Errorf("isIgnoredPath(%q) = %v, want %v", path, got, want)
		}
	}
}

func TestHashFile_DeterministicAndSizeCorrect(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "sample.txt")
	content := []byte("hello compliance")
	if err := os.WriteFile(path, content, 0o644); err != nil {
		t.Fatal(err)
	}

	hash1, size1, err := hashFile(path)
	if err != nil {
		t.Fatalf("hashFile: %v", err)
	}
	hash2, _, _ := hashFile(path)

	if hash1 != hash2 {
		t.Error("hashFile is not deterministic for identical content")
	}
	if size1 != int64(len(content)) {
		t.Errorf("size = %d, want %d", size1, len(content))
	}
}

func TestFileIntegrityCollector_Collect_FindsWrittenFile(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "watched.conf"), []byte("setting=1"), 0o644); err != nil {
		t.Fatal(err)
	}

	c := &FileIntegrityCollector{WatchPaths: []string{dir}}
	facts, err := c.Collect(nil)
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}

	files, ok := facts["files"].([]FileHash)
	if !ok || len(files) != 1 {
		t.Fatalf("facts[files] = %v, want exactly 1 entry", facts["files"])
	}
	if files[0].Hash == "" {
		t.Error("FileHash.Hash is empty")
	}
}

func TestFileIntegrityCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*FileIntegrityCollector)(nil)
	c := NewFileIntegrityCollector()
	if c.Domain() != "file_integrity" {
		t.Errorf("Domain() = %q, want file_integrity", c.Domain())
	}
	if c.Interval() <= 0 {
		t.Error("Interval() must be > 0 — FIM must not run every heartbeat")
	}
}
