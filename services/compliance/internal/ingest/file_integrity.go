package ingest

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
