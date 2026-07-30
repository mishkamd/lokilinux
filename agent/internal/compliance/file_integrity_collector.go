package compliance

import (
	"context"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"time"

	"lukechampine.com/blake3"
)

// fileIntegrityWatchPaths is the default file-integrity watch list per
// docs/compliance/03-AGENT-PLUGIN-SDK.md §5.
var fileIntegrityWatchPaths = []string{
	"/etc", "/usr/lib/systemd", "/boot", "/etc/ssh", "/etc/pam.d",
	"/etc/security", "/etc/audit", "/etc/sysctl.d",
}

// FileIntegrityCollector hashes (BLAKE3) every file under the watch list.
// It runs on its own 15-minute cadence, not every heartbeat — a full
// filesystem walk over /etc is comparatively expensive at 100k-agent
// scale, and file contents don't change on a 60s timescale.
//
// ponytail: Ignores is a static list set at construction, not yet pulled
// from the effective baseline's file_integrity_ignores
// (docs/compliance/01-DATA-MODEL.md §5) — the agent has no baseline-
// delivery channel yet (that rides the same domain_full/policy wire this
// module is still building). Wire baseline-driven ignores here once that
// delivery path exists; until then an operator can still set Ignores
// directly when constructing the collector.
type FileIntegrityCollector struct {
	WatchPaths []string
	Ignores    []string
}

func NewFileIntegrityCollector() *FileIntegrityCollector {
	return &FileIntegrityCollector{WatchPaths: fileIntegrityWatchPaths}
}

func (c *FileIntegrityCollector) Domain() string { return "file_integrity" }

func (c *FileIntegrityCollector) Interval() time.Duration { return 15 * time.Minute }

// FileHash is one watched file's current content hash.
type FileHash struct {
	Path string `json:"path"`
	Hash string `json:"hash"`
	Size int64  `json:"size"`
}

func (c *FileIntegrityCollector) Collect(ctx context.Context) (Facts, error) {
	var files []FileHash
	for _, root := range c.WatchPaths {
		_ = filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return nil // unreadable subtree — skip, don't abort the whole walk
			}
			if d.IsDir() {
				return nil
			}
			if isIgnoredPath(path, c.Ignores) {
				return nil
			}
			hash, size, err := hashFile(path)
			if err != nil {
				return nil // unreadable file (permissions, gone since readdir) — skip
			}
			files = append(files, FileHash{Path: path, Hash: hash, Size: size})
			return nil
		})
	}
	return Facts{"files": files}, nil
}

// isIgnoredPath matches a path against file_integrity_ignores entries,
// treating each entry as either an exact glob pattern (filepath.Match) or
// a path prefix — the latter lets an ignore entry cover a whole directory
// ("/etc/some-noisy-dir") without needing a trailing "/*" glob.
func isIgnoredPath(path string, ignores []string) bool {
	for _, pattern := range ignores {
		if matched, _ := filepath.Match(pattern, path); matched {
			return true
		}
		if strings.HasPrefix(path, strings.TrimSuffix(pattern, "/")+"/") {
			return true
		}
	}
	return false
}

// hashFile reads the whole file into memory before hashing — /etc's
// largest files (kernels under /boot aside) are comparatively small, so
// this matches canonical.go's Hash function exactly (BLAKE3 over the full
// byte slice) rather than adding a second, streaming hash code path.
func hashFile(path string) (string, int64, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", 0, err
	}
	sum := blake3.Sum256(data)
	return hex.EncodeToString(sum[:]), int64(len(data)), nil
}
