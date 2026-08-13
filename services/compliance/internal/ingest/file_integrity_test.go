package ingest

import (
	"testing"

	"github.com/lokilinux/compliance/internal/storage"
)

func i32(v int32) *int32 { return &v }

func TestDiffFileIntegrity_CreatedModifiedDeleted(t *testing.T) {
	previous := map[string]storage.ExistingFileHash{
		"/etc/passwd":     {Hash: "hash-a"},
		"/etc/sudoers":    {Hash: "hash-b"},
		"/etc/removed.cf": {Hash: "hash-c"},
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
			map[string]any{"path": "/etc/passwd", "hash": "abc123", "size": float64(1234), "mode": float64(0644), "uid": float64(0), "gid": float64(0)},
			map[string]any{"path": "/etc/bad_entry_no_hash", "hash": ""},
			"not even a map",
			map[string]any{"hash": "orphan-no-path"},
		},
	}

	got := parseAgentFileHashes(facts)
	if len(got) != 1 {
		t.Fatalf("got %d entries, want 1 (malformed entries skipped): %+v", len(got), got)
	}
	if got[0].Path != "/etc/passwd" || got[0].Hash != "abc123" || got[0].Size != 1234 || got[0].Mode != 0644 {
		t.Errorf("got %+v, want {/etc/passwd abc123 1234 mode=0644}", got[0])
	}
}

func TestParseAgentFileHashes_MissingFilesKey(t *testing.T) {
	if got := parseAgentFileHashes(map[string]any{}); got != nil {
		t.Errorf("got %v, want nil", got)
	}
}

func TestFilterIgnored_MatchingPatternDropped(t *testing.T) {
	changes := []FileChange{
		{Path: "/var/log/messages", ChangeKind: "MODIFIED"},
		{Path: "/etc/ssh/sshd_config", ChangeKind: "MODIFIED"},
	}
	out := filterIgnored(changes, []string{"/var/log/*"})
	if len(out) != 1 || out[0].Path != "/etc/ssh/sshd_config" {
		t.Fatalf("filterIgnored = %+v, want only /etc/ssh/sshd_config", out)
	}
}

func TestFilterIgnored_NoPatternsReturnsAllUnchanged(t *testing.T) {
	changes := []FileChange{{Path: "/etc/passwd", ChangeKind: "MODIFIED"}}
	out := filterIgnored(changes, nil)
	if len(out) != 1 {
		t.Fatalf("filterIgnored with no patterns = %v, want unchanged", out)
	}
}

func TestFilterIgnored_MultiplePatterns(t *testing.T) {
	changes := []FileChange{
		{Path: "/run/lock/foo", ChangeKind: "CREATED"},
		{Path: "/proc/self/status", ChangeKind: "MODIFIED"},
		{Path: "/etc/sudoers", ChangeKind: "MODIFIED"},
	}
	out := filterIgnored(changes, []string{"/run/*", "/proc/*"})
	if len(out) != 1 || out[0].Path != "/etc/sudoers" {
		t.Fatalf("filterIgnored = %+v, want only /etc/sudoers", out)
	}
}

func TestFilterIgnored_MalformedPatternNeverMatchesButDoesNotPanic(t *testing.T) {
	changes := []FileChange{{Path: "/etc/passwd", ChangeKind: "MODIFIED"}}
	out := filterIgnored(changes, []string{"["}) // invalid glob pattern
	if len(out) != 1 {
		t.Fatalf("filterIgnored with malformed pattern = %v, want the change kept (pattern treated as non-matching)", out)
	}
}

func TestDiffFileIntegrity_PermissionChanged(t *testing.T) {
	previous := map[string]storage.ExistingFileHash{
		"/etc/shadow": {Hash: "same-hash", Mode: i32(0400), UID: i32(0), GID: i32(0)},
	}
	current := []AgentFileHash{
		{Path: "/etc/shadow", Hash: "same-hash", Mode: 0644, UID: 0, GID: 0}, // same content, world-readable now
	}

	changes := diffFileIntegrity(previous, current)
	if len(changes) != 1 {
		t.Fatalf("got %d changes, want 1: %+v", len(changes), changes)
	}
	c := changes[0]
	if c.ChangeKind != "PERMISSION_CHANGED" {
		t.Errorf("ChangeKind = %s, want PERMISSION_CHANGED", c.ChangeKind)
	}
	if c.OldMode == nil || *c.OldMode != 0400 || c.NewMode == nil || *c.NewMode != 0644 {
		t.Errorf("mode = %+v -> %+v, want 0400 -> 0644", c.OldMode, c.NewMode)
	}
}

func TestDiffFileIntegrity_OwnerChanged(t *testing.T) {
	previous := map[string]storage.ExistingFileHash{
		"/etc/sudoers.d/custom": {Hash: "same-hash", Mode: i32(0440), UID: i32(0), GID: i32(0)},
	}
	current := []AgentFileHash{
		{Path: "/etc/sudoers.d/custom", Hash: "same-hash", Mode: 0440, UID: 1000, GID: 0}, // same content+mode, owner changed
	}

	changes := diffFileIntegrity(previous, current)
	if len(changes) != 1 {
		t.Fatalf("got %d changes, want 1: %+v", len(changes), changes)
	}
	c := changes[0]
	if c.ChangeKind != "OWNER_CHANGED" {
		t.Errorf("ChangeKind = %s, want OWNER_CHANGED", c.ChangeKind)
	}
	if c.OldUID == nil || *c.OldUID != 0 || c.NewUID == nil || *c.NewUID != 1000 {
		t.Errorf("uid = %+v -> %+v, want 0 -> 1000", c.OldUID, c.NewUID)
	}
}

func TestDiffFileIntegrity_ContentChangeTakesPriorityOverModeChange(t *testing.T) {
	previous := map[string]storage.ExistingFileHash{
		"/etc/passwd": {Hash: "old-hash", Mode: i32(0644), UID: i32(0), GID: i32(0)},
	}
	current := []AgentFileHash{
		{Path: "/etc/passwd", Hash: "new-hash", Mode: 0600, UID: 0, GID: 0}, // content AND mode changed
	}

	changes := diffFileIntegrity(previous, current)
	if len(changes) != 1 || changes[0].ChangeKind != "MODIFIED" {
		t.Fatalf("ChangeKind = %+v, want MODIFIED (content change takes priority)", changes)
	}
}

func TestDiffFileIntegrity_NoChangeWhenEverythingMatches(t *testing.T) {
	previous := map[string]storage.ExistingFileHash{
		"/etc/passwd": {Hash: "h", Mode: i32(0644), UID: i32(0), GID: i32(0)},
	}
	current := []AgentFileHash{
		{Path: "/etc/passwd", Hash: "h", Mode: 0644, UID: 0, GID: 0},
	}
	if changes := diffFileIntegrity(previous, current); len(changes) != 0 {
		t.Fatalf("got %+v, want no changes", changes)
	}
}
