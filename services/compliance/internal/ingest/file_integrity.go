package ingest

import (
	"path/filepath"
	"strings"

	"github.com/lokilinux/compliance/internal/storage"
)

// AgentFileHash is one entry of a file_integrity snapshot's "files" array —
// mirrors agent/internal/compliance.FileHash's JSON shape exactly
// ({"path","hash","size","mode","uid","gid","mtime"}).
type AgentFileHash struct {
	Path string
	Hash string
	Size int64
	Mode int32
	UID  int32
	GID  int32
}

// FileChange is one detected per-file change, ready for
// storage.InsertFileChange/UpsertFileHash/DeleteFileHash. Mode/UID/GID
// pointers are nil when that piece of metadata didn't change (or isn't
// known, e.g. DELETED has no "new" side) — nil serializes to SQL NULL,
// matching file_changes' nullable old_mode/new_mode/old_uid/... columns
// (migration 025).
type FileChange struct {
	Path       string
	OldHash    string
	NewHash    string
	NewSize    int64
	ChangeKind string // CREATED/MODIFIED/DELETED/PERMISSION_CHANGED/OWNER_CHANGED

	OldMode, NewMode *int32
	OldUID, NewUID   *int32
	OldGID, NewGID   *int32

	NewModeVal, NewUIDVal, NewGIDVal int32 // current values, always set — for UpsertFileHash regardless of change_kind
}

// diffFileIntegrity compares the agent-reported current file list against
// the previously stored per-file hashes+metadata and returns exactly the
// changes — pure function, no I/O, so it's testable without a real
// database. Content hash changes take priority over metadata-only changes:
// a file whose content AND permissions both changed is reported as
// MODIFIED (the security-relevant signal), not PERMISSION_CHANGED.
func diffFileIntegrity(previous map[string]storage.ExistingFileHash, current []AgentFileHash) []FileChange {
	var changes []FileChange
	seen := make(map[string]struct{}, len(current))

	for _, f := range current {
		seen[f.Path] = struct{}{}
		prev, existed := previous[f.Path]

		newMode, newUID, newGID := f.Mode, f.UID, f.GID
		switch {
		case !existed:
			changes = append(changes, FileChange{
				Path: f.Path, NewHash: f.Hash, NewSize: f.Size, ChangeKind: "CREATED",
				NewMode: &newMode, NewUID: &newUID, NewGID: &newGID,
				NewModeVal: newMode, NewUIDVal: newUID, NewGIDVal: newGID,
			})
		case prev.Hash != f.Hash:
			c := FileChange{
				Path: f.Path, OldHash: prev.Hash, NewHash: f.Hash, NewSize: f.Size, ChangeKind: "MODIFIED",
				NewMode: &newMode, NewUID: &newUID, NewGID: &newGID,
				NewModeVal: newMode, NewUIDVal: newUID, NewGIDVal: newGID,
			}
			c.OldMode, c.OldUID, c.OldGID = prev.Mode, prev.UID, prev.GID
			changes = append(changes, c)
		case prev.Mode != nil && *prev.Mode != f.Mode:
			c := FileChange{
				Path: f.Path, OldHash: prev.Hash, NewHash: f.Hash, NewSize: f.Size, ChangeKind: "PERMISSION_CHANGED",
				NewMode: &newMode, NewUID: &newUID, NewGID: &newGID, OldMode: prev.Mode,
				NewModeVal: newMode, NewUIDVal: newUID, NewGIDVal: newGID,
			}
			changes = append(changes, c)
		case (prev.UID != nil && *prev.UID != f.UID) || (prev.GID != nil && *prev.GID != f.GID):
			c := FileChange{
				Path: f.Path, OldHash: prev.Hash, NewHash: f.Hash, NewSize: f.Size, ChangeKind: "OWNER_CHANGED",
				NewMode: &newMode, NewUID: &newUID, NewGID: &newGID, OldUID: prev.UID, OldGID: prev.GID,
				NewModeVal: newMode, NewUIDVal: newUID, NewGIDVal: newGID,
			}
			changes = append(changes, c)
		}
	}

	for path, prev := range previous {
		if _, ok := seen[path]; !ok {
			changes = append(changes, FileChange{
				Path: path, OldHash: prev.Hash, ChangeKind: "DELETED",
				OldMode: prev.Mode, OldUID: prev.UID, OldGID: prev.GID,
			})
		}
	}

	return changes
}

// filterIgnored drops changes whose path matches any of patterns
// (file_integrity_ignores.path_pattern — docs/compliance §11's example
// `/var/log/*`, `/run/*`, ...). filepath.Match's glob syntax is the whole
// pattern language for v1: it covers every example in the brief without
// needing a heavier matcher, and path.Match errors (a malformed pattern)
// are treated as "does not match" rather than failing the whole ingest —
// one bad admin-entered pattern must not block file integrity processing
// fleet-wide.
func filterIgnored(changes []FileChange, patterns []string) []FileChange {
	if len(patterns) == 0 {
		return changes
	}
	out := make([]FileChange, 0, len(changes))
	for _, c := range changes {
		if !matchesAny(c.Path, patterns) {
			out = append(out, c)
		}
	}
	return out
}

// matchesAny checks path against each pattern. A pattern ending in "/*"
// (every example in docs/compliance §11: /var/log/*, /run/*, /proc/*,
// /sys/*) matches every path under that directory, recursively — the
// admin's intent for "ignore this whole tree," not filepath.Match's literal
// single-segment glob semantics. Any other pattern falls back to
// filepath.Match for finer-grained cases (e.g. "*.tmp").
func matchesAny(path string, patterns []string) bool {
	for _, p := range patterns {
		if prefix, ok := strings.CutSuffix(p, "/*"); ok {
			if strings.HasPrefix(path, prefix+"/") {
				return true
			}
			continue
		}
		if ok, err := filepath.Match(p, path); err == nil && ok {
			return true
		}
	}
	return false
}

// parseAgentFileHashes decodes the "files" array from a file_integrity
// snapshot's Facts (already json.Unmarshal'd into map[string]any by
// parseSnapshotMessage, so JSON objects/arrays/numbers arrive as
// map[string]any/[]any/float64). Malformed entries are skipped rather than
// failing the whole ingest — one bad record from a misbehaving collector
// shouldn't block every other file's drift detection. mode/uid/gid default
// to 0 when absent (an agent older than F11 that hasn't reported them yet)
// rather than erroring — a stale agent must not break file integrity
// entirely, it just won't produce PERMISSION_CHANGED/OWNER_CHANGED events
// until it upgrades.
func parseAgentFileHashes(facts map[string]any) []AgentFileHash {
	raw, ok := facts["files"].([]any)
	if !ok {
		return nil
	}
	var out []AgentFileHash
	for _, item := range raw {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		path, _ := m["path"].(string)
		hash, _ := m["hash"].(string)
		if path == "" || hash == "" {
			continue
		}
		size, _ := m["size"].(float64)
		mode, _ := m["mode"].(float64)
		uid, _ := m["uid"].(float64)
		gid, _ := m["gid"].(float64)
		out = append(out, AgentFileHash{
			Path: path, Hash: hash, Size: int64(size),
			Mode: int32(mode), UID: int32(uid), GID: int32(gid),
		})
	}
	return out
}
