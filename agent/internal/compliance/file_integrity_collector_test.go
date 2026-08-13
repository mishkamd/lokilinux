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

func TestFileIntegrityCollector_Collect_ReportsModeUIDGIDMTime(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "watched.conf")
	if err := os.WriteFile(path, []byte("setting=1"), 0o640); err != nil {
		t.Fatal(err)
	}

	c := &FileIntegrityCollector{WatchPaths: []string{dir}}
	facts, err := c.Collect(nil)
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}
	files := facts["files"].([]FileHash)
	if len(files) != 1 {
		t.Fatalf("got %d files, want 1", len(files))
	}
	f := files[0]
	if f.Mode != 0o640 {
		t.Errorf("Mode = %o, want 0640", f.Mode)
	}
	if f.MTime.IsZero() {
		t.Error("MTime is zero, want the file's actual mtime")
	}
	// UID/GID: whatever this test process's euid/egid are (files it just
	// created), just confirm statOwnership actually populated something
	// rather than always returning the -1,-1 fallback.
	if f.UID < 0 || f.GID < 0 {
		t.Errorf("UID/GID = %d/%d, want real non-negative values from syscall.Stat_t", f.UID, f.GID)
	}
}

func TestNewFileIntegrityCollectorWithConfig_EmptyWatchPathsFallsBackToDefault(t *testing.T) {
	c := NewFileIntegrityCollectorWithConfig(nil, []string{"/some/ignore"})
	if len(c.WatchPaths) != len(fileIntegrityWatchPaths) {
		t.Errorf("WatchPaths = %v, want the built-in default when config passes none", c.WatchPaths)
	}
	if len(c.Ignores) != 1 || c.Ignores[0] != "/some/ignore" {
		t.Errorf("Ignores = %v, want [/some/ignore]", c.Ignores)
	}
}

func TestNewFileIntegrityCollectorWithConfig_CustomWatchPathsOverrideDefault(t *testing.T) {
	c := NewFileIntegrityCollectorWithConfig([]string{"/custom/path"}, nil)
	if len(c.WatchPaths) != 1 || c.WatchPaths[0] != "/custom/path" {
		t.Errorf("WatchPaths = %v, want [/custom/path]", c.WatchPaths)
	}
}

func TestBuildRegistry_ReplacesOnlyFileIntegrityCollector(t *testing.T) {
	registry := BuildRegistry([]string{"/custom/path"}, []string{"/ignore/me"})
	if len(registry) != len(Registry) {
		t.Fatalf("BuildRegistry length = %d, want %d (same collector count as Registry)", len(registry), len(Registry))
	}

	var found bool
	for _, c := range registry {
		fic, ok := c.(*FileIntegrityCollector)
		if !ok {
			continue
		}
		found = true
		if len(fic.WatchPaths) != 1 || fic.WatchPaths[0] != "/custom/path" {
			t.Errorf("configured FileIntegrityCollector.WatchPaths = %v, want [/custom/path]", fic.WatchPaths)
		}
	}
	if !found {
		t.Fatal("BuildRegistry dropped the FileIntegrityCollector entirely")
	}
}
