package ingest

import (
	"path/filepath"
	"strings"
)

// AgentFileHash is one entry of a file_integrity snapshot's "files" array —
// mirrors agent/internal/compliance.FileHash's JSON shape exactly
// ({"path":..., "hash":..., "size":...}).
type AgentFileHash struct {
	Path string
	Hash string
	Size int64
}

// FileChange is one detected per-file change, ready for
// storage.InsertFileChange/UpsertFileHash/DeleteFileHash.
type FileChange struct {
	Path       string
	OldHash    string
	NewHash    string
	NewSize    int64
	ChangeKind string // CREATED/MODIFIED/DELETED — matches file_changes.change_kind
}

// diffFileIntegrity compares the agent-reported current file list against
// the previously stored per-file hashes and returns exactly the changes —
// pure function, no I/O, so it's testable without a real database.
// PERMISSION_CHANGED (migration 017's fourth change_kind) isn't produced
// here — the agent's FileHash doesn't report mode/uid/gid today
// (agent/internal/compliance/file_integrity_collector.go), so there's
// nothing to compare; add it once the collector captures that.
func diffFileIntegrity(previous map[string]string, current []AgentFileHash) []FileChange {
	var changes []FileChange
	seen := make(map[string]struct{}, len(current))

	for _, f := range current {
		seen[f.Path] = struct{}{}
		oldHash, existed := previous[f.Path]
		switch {
		case !existed:
			changes = append(changes, FileChange{Path: f.Path, NewHash: f.Hash, NewSize: f.Size, ChangeKind: "CREATED"})
		case oldHash != f.Hash:
			changes = append(changes, FileChange{Path: f.Path, OldHash: oldHash, NewHash: f.Hash, NewSize: f.Size, ChangeKind: "MODIFIED"})
		}
	}

	for path, oldHash := range previous {
		if _, ok := seen[path]; !ok {
			changes = append(changes, FileChange{Path: path, OldHash: oldHash, ChangeKind: "DELETED"})
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
// shouldn't block every other file's drift detection.
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
		out = append(out, AgentFileHash{Path: path, Hash: hash, Size: int64(size)})
	}
	return out
}
