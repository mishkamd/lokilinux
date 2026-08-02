package ingest

import "testing"

func TestDiffFileIntegrity_CreatedModifiedDeleted(t *testing.T) {
	previous := map[string]string{
		"/etc/passwd":     "hash-a",
		"/etc/sudoers":    "hash-b",
		"/etc/removed.cf": "hash-c",
	}
	current := []AgentFileHash{
		{Path: "/etc/passwd", Hash: "hash-a", Size: 100},   // unchanged — not in result
		{Path: "/etc/sudoers", Hash: "hash-b2", Size: 200}, // modified
		{Path: "/etc/new.cf", Hash: "hash-d", Size: 50},    // created
	}

	changes := diffFileIntegrity(previous, current)
	if len(changes) != 3 {
		t.Fatalf("got %d changes, want 3: %+v", len(changes), changes)
	}

	byPath := map[string]FileChange{}
	for _, c := range changes {
		byPath[c.Path] = c
	}

	if c := byPath["/etc/sudoers"]; c.ChangeKind != "MODIFIED" || c.OldHash != "hash-b" || c.NewHash != "hash-b2" {
		t.Errorf("/etc/sudoers = %+v, want MODIFIED hash-b -> hash-b2", c)
	}
	if c := byPath["/etc/new.cf"]; c.ChangeKind != "CREATED" || c.NewHash != "hash-d" || c.OldHash != "" {
		t.Errorf("/etc/new.cf = %+v, want CREATED with no OldHash", c)
	}
	if c := byPath["/etc/removed.cf"]; c.ChangeKind != "DELETED" || c.OldHash != "hash-c" || c.NewHash != "" {
		t.Errorf("/etc/removed.cf = %+v, want DELETED with no NewHash", c)
	}
	if _, present := byPath["/etc/passwd"]; present {
		t.Error("/etc/passwd unchanged — must not appear in the diff")
	}
}

func TestDiffFileIntegrity_EmptyBothSides(t *testing.T) {
	if changes := diffFileIntegrity(nil, nil); len(changes) != 0 {
		t.Errorf("got %v, want no changes", changes)
	}
}

func TestDiffFileIntegrity_FirstEverSnapshotIsAllCreated(t *testing.T) {
	current := []AgentFileHash{{Path: "/etc/a", Hash: "h1"}, {Path: "/etc/b", Hash: "h2"}}
	changes := diffFileIntegrity(nil, current)
	if len(changes) != 2 {
		t.Fatalf("got %d changes, want 2", len(changes))
	}
	for _, c := range changes {
		if c.ChangeKind != "CREATED" {
			t.Errorf("change %+v, want ChangeKind=CREATED for a first-ever snapshot", c)
		}
	}
}

func TestParseAgentFileHashes(t *testing.T) {
	facts := map[string]any{
		"files": []any{
			map[string]any{"path": "/etc/passwd", "hash": "abc123", "size": float64(1234)},
			map[string]any{"path": "/etc/bad_entry_no_hash", "hash": ""},
			"not even a map",
			map[string]any{"hash": "orphan-no-path"},
		},
	}

	got := parseAgentFileHashes(facts)
	if len(got) != 1 {
		t.Fatalf("got %d entries, want 1 (malformed entries skipped): %+v", len(got), got)
	}
	if got[0].Path != "/etc/passwd" || got[0].Hash != "abc123" || got[0].Size != 1234 {
		t.Errorf("got %+v, want {/etc/passwd abc123 1234}", got[0])
	}
}

func TestParseAgentFileHashes_MissingFilesKey(t *testing.T) {
	if got := parseAgentFileHashes(map[string]any{}); got != nil {
		t.Errorf("got %v, want nil", got)
	}
}
