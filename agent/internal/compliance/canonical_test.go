package compliance

import (
	"encoding/hex"
	"encoding/json"
	"testing"

	"lukechampine.com/blake3"
)

// TestCanonicalJSON_KeyOrderIndependent locks the property everything else
// in this package depends on: two Facts values built with keys inserted in
// a different order must hash identically. If this ever breaks (e.g.
// someone swaps encoding/json for a library that doesn't sort map keys),
// delta-sync would treat an unchanged config as changed on every heartbeat.
func TestCanonicalJSON_KeyOrderIndependent(t *testing.T) {
	a := Facts{"b": "2", "a": "1", "c": "3"}
	b := Facts{"c": "3", "a": "1", "b": "2"}

	hashA, err := Hash(a)
	if err != nil {
		t.Fatalf("Hash(a) error = %v", err)
	}
	hashB, err := Hash(b)
	if err != nil {
		t.Fatalf("Hash(b) error = %v", err)
	}
	if hashA != hashB {
		t.Errorf("Hash(a) = %s, Hash(b) = %s, want equal for the same content in different insertion order", hashA, hashB)
	}
}

func TestCanonicalJSON_DifferentContentDifferentHash(t *testing.T) {
	a := Facts{"PermitRootLogin": "no"}
	b := Facts{"PermitRootLogin": "yes"}

	hashA, _ := Hash(a)
	hashB, _ := Hash(b)
	if hashA == hashB {
		t.Errorf("Hash produced the same digest for different content: %s", hashA)
	}
}

func TestCanonicalJSON_NestedMapsAlsoSorted(t *testing.T) {
	a := Facts{"outer": map[string]any{"z": 1, "a": 2}}
	b := Facts{"outer": map[string]any{"a": 2, "z": 1}}

	hashA, _ := Hash(a)
	hashB, _ := Hash(b)
	if hashA != hashB {
		t.Errorf("nested map key order affected the hash: %s != %s", hashA, hashB)
	}
}

func TestHash_ReturnsHexString(t *testing.T) {
	h, err := Hash(Facts{"x": "y"})
	if err != nil {
		t.Fatalf("Hash error = %v", err)
	}
	if len(h) != 64 { // BLAKE3-256 -> 32 bytes -> 64 hex chars
		t.Errorf("Hash length = %d, want 64 (32-byte digest hex-encoded)", len(h))
	}
}

// TestNormalize_StructFieldsSurviveServerRoundTrip is the regression test
// for the actual production incident: Facts containing a typed struct
// (every real collector with more than flat map[string]string — mounts,
// users, processes, pam, systemd_services, certificates, file_integrity,
// open_ports) hashed differently on the agent (struct fields marshal in
// declaration order) than on the compliance service (which only ever sees
// JSON off the wire, so every struct has already collapsed into
// map[string]any, marshaled with sorted keys). That mismatch rejected 100%
// of snapshots for all 8 domains, forever, and fed a NATS redelivery loop
// that pinned a CPU core for days. Every other test in this file uses only
// flat maps, which round-trip identically either way — that's exactly why
// this bug shipped unnoticed.
//
// Normalize() is the fix: round-trip Facts through JSON before hashing, so
// the agent hashes the same shape the server reconstructs. This test
// doesn't call Normalize's own implementation to check itself — it
// independently reconstructs what the server does (decode off the wire,
// re-marshal) and asserts the two hashes match.
func TestNormalize_StructFieldsSurviveServerRoundTrip(t *testing.T) {
	facts := Facts{
		"mounts": []Mount{
			{Source: "/dev/sda1", Target: "/", FSType: "ext4", Options: []string{"rw", "relatime"}},
			{Source: "tmpfs", Target: "/tmp", FSType: "tmpfs", Options: []string{"rw", "nosuid", "nodev"}},
		},
	}

	normalized, err := Normalize(facts)
	if err != nil {
		t.Fatalf("Normalize error = %v", err)
	}
	agentHash, err := Hash(normalized)
	if err != nil {
		t.Fatalf("Hash(normalized) error = %v", err)
	}

	// What the server actually does: it never has Go structs, only the
	// JSON the agent sent — decode, then re-encode to hash.
	wire, err := json.Marshal(facts)
	if err != nil {
		t.Fatalf("marshal error = %v", err)
	}
	var serverFacts map[string]any
	if err := json.Unmarshal(wire, &serverFacts); err != nil {
		t.Fatalf("unmarshal error = %v", err)
	}
	serverBody, err := json.Marshal(serverFacts)
	if err != nil {
		t.Fatalf("server marshal error = %v", err)
	}
	serverSum := blake3.Sum256(serverBody)
	serverHash := hex.EncodeToString(serverSum[:])

	if agentHash != serverHash {
		t.Errorf("agent hash %s != server-reconstructed hash %s — struct field order breaks verification", agentHash, serverHash)
	}

	// And the bug this replaced: hashing the raw (non-normalized) struct
	// directly must NOT match the server's reconstruction — if it does,
	// Mount's fields happened to already be alphabetical and this assertion
	// is no longer exercising the regression; add a field to break the tie.
	rawHash, err := Hash(facts)
	if err != nil {
		t.Fatalf("Hash(facts) error = %v", err)
	}
	if rawHash == serverHash {
		t.Fatal("raw (non-normalized) hash unexpectedly matches server reconstruction — this test no longer exercises the struct-field-order bug it's meant to guard")
	}
}
