package compliance

import (
	"context"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"lukechampine.com/blake3"
)

// fileIntegrityWatchPaths is the default file-integrity watch list — just
// /etc, since it's the directory that actually matters for security-relevant
// config drift on most fleets and won't surprise anyone with a 15-minute
// full-filesystem walk. Operators add /boot, /usr/lib/systemd, or anything
// else via the global/per-server scope UI (docs/compliance/11a-FRONTEND-PAGES.md
// §3.4) — the signed fim_config channel (fimconfig.go) — or, for a single
// host without control-plane access, the local agent.yaml override.
var fileIntegrityWatchPaths = []string{"/etc"}

// maxHashableFileBytes caps how large a single file can be before the
// collector skips hashing it entirely.
//
// ponytail: 10MB flat ceiling, no streaming hash — hashFile still loads the
// whole file into RAM (see its own comment). Fine while watch lists are
// /etc-shaped; once an operator points this at something that legitimately
// holds large files (e.g. /var/lib/some-app), swap hashFile for a streaming
// blake3.Hasher over an *os.File instead of raising this constant.
const maxHashableFileBytes = 10 * 1024 * 1024

// FileIntegrityCollector hashes (BLAKE3) every file under the watch list.
// It runs on its own 15-minute cadence, not every heartbeat — a full
// filesystem walk over /etc is comparatively expensive at 100k-agent
// scale, and file contents don't change on a 60s timescale.
//
// watchPaths/ignores start from the agent's own YAML config (agent/internal/
// config — FileIntegrityConfig), falling back to fileIntegrityWatchPaths/no
// ignores when unset (see BuildRegistry). A signed fim_config document
// delivered over the heartbeat (fimconfig.go, manager.go handleResponse)
// overrides both via SetPaths — that's the control-plane channel described
// in docs/compliance/11a-FRONTEND-PAGES.md §3.4. Server-side
// file_integrity_ignores (docs/compliance/01-DATA-MODEL.md §5) is a
// separate, GLOBAL-only, post-ingest filter and is not consulted here.
type FileIntegrityCollector struct {
	mu         sync.RWMutex
	watchPaths []string
	ignores    []string
}

func NewFileIntegrityCollector() *FileIntegrityCollector {
	return &FileIntegrityCollector{watchPaths: fileIntegrityWatchPaths}
}

// NewFileIntegrityCollectorWithConfig builds a collector using operator-
// configured watch/ignore paths, falling back to the built-in default watch
// list when watchPaths is empty (an empty ignores list is a legitimate
// choice, not "unset", so it's never defaulted).
func NewFileIntegrityCollectorWithConfig(watchPaths, ignores []string) *FileIntegrityCollector {
	if len(watchPaths) == 0 {
		watchPaths = fileIntegrityWatchPaths
	}
	return &FileIntegrityCollector{watchPaths: watchPaths, ignores: ignores}
}

// Paths returns the collector's current watch/ignore lists — used by tests
// and status/debug surfaces. Callers must not mutate the returned slices.
func (c *FileIntegrityCollector) Paths() (watchPaths, ignores []string) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.watchPaths, c.ignores
}

// SetPaths replaces the watch/ignore lists in place — used when a signed
// fim_config document arrives over the heartbeat (see fimconfig.go) so the
// next Collect() picks up the new scope without rebuilding the collector or
// the registry it lives in.
func (c *FileIntegrityCollector) SetPaths(watchPaths, ignores []string) {
	if len(watchPaths) == 0 {
		watchPaths = fileIntegrityWatchPaths
	}
	c.mu.Lock()
	c.watchPaths = watchPaths
	c.ignores = ignores
	c.mu.Unlock()
}

func (c *FileIntegrityCollector) Domain() string { return "file_integrity" }

func (c *FileIntegrityCollector) Interval() time.Duration { return 15 * time.Minute }

// FileHash is one watched file's current content hash plus the metadata
// migration 025's file_changes.old_mode/new_mode/old_uid/new_uid/old_gid/
// new_gid columns exist to record — PERMISSION_CHANGED/OWNER_CHANGED
// (services/compliance/internal/ingest/file_integrity.go) had nothing to
// compare until this collector reported them.
type FileHash struct {
	Path  string    `json:"path"`
	Hash  string    `json:"hash"`
	Size  int64     `json:"size"`
	Mode  uint32    `json:"mode"`
	UID   int       `json:"uid"`
	GID   int       `json:"gid"`
	MTime time.Time `json:"mtime"`
}

func (c *FileIntegrityCollector) Collect(ctx context.Context) (Facts, error) {
	c.mu.RLock()
	watchPaths := c.watchPaths
	ignores := c.ignores
	c.mu.RUnlock()

	var files []FileHash
	seen := make(map[string]struct{})
	for _, root := range watchPaths {
		_ = filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return nil // unreadable subtree — skip, don't abort the whole walk
			}
			if d.IsDir() {
				return nil
			}
			if _, dup := seen[path]; dup {
				return nil // already hashed via an overlapping watch root
			}
			if isIgnoredPath(path, ignores) {
				return nil
			}
			info, err := d.Info()
			if err != nil {
				return nil // gone since readdir, or permission error — skip
			}
			if info.Size() > maxHashableFileBytes {
				return nil
			}
			hash, size, err := hashFile(path)
			if err != nil {
				return nil // unreadable file (permissions, gone since readdir) — skip
			}
			seen[path] = struct{}{}
			uid, gid := statOwnership(info)
			files = append(files, FileHash{
				Path: path, Hash: hash, Size: size,
				Mode: uint32(info.Mode().Perm()), UID: uid, GID: gid, MTime: info.ModTime().UTC(),
			})
			return nil
		})
	}
	return Facts{"files": files}, nil
}

// statOwnership extracts uid/gid from the platform-specific portion of
// os.FileInfo — populated on every Linux syscall.Stat_t, which is all this
// agent targets (systemd-run-based job execution elsewhere in this package
// already assumes Linux). Returns -1, -1 if the underlying Sys() value
// isn't a *syscall.Stat_t, so a test double FileInfo degrades safely
// instead of panicking.
func statOwnership(info os.FileInfo) (uid, gid int) {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return -1, -1
	}
	return int(stat.Uid), int(stat.Gid)
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
