package compliance

import (
	"encoding/hex"
	"encoding/json"
	"fmt"

	"lukechampine.com/blake3"
)

// Normalize round-trips facts through JSON (marshal then unmarshal into a
// fresh map[string]any) before it's hashed or cached.
//
// encoding/json sorts map[string]T keys alphabetically at every nesting
// level when marshaling — that guarantee holds for maps, but NOT for struct
// fields, which marshal in declaration order. Facts values from collectors
// with typed structs (mounts, users, processes, pam, systemd_services,
// certificates, file_integrity, open_ports — anything nesting a struct or
// []struct rather than only maps/slices-of-primitives) therefore encoded in
// declaration order on the agent. The server only ever sees Facts after a
// JSON decode, where every struct has already collapsed into map[string]any
// — so it re-marshals in sorted order and computes a different hash for the
// exact same data, on every single snapshot. Confirmed live: this was
// rejecting all 8 struct-shaped domains, deterministically, forever.
//
// Round-tripping through JSON here makes the agent hash the same shape the
// server reconstructs, so CanonicalJSON/Hash are proper content-addressable
// (this is what content-addressable storage and delta-sync,
// docs/compliance/04-PROTOCOL.md §3, actually need) instead of merely
// stable-per-process.
func Normalize(facts Facts) (Facts, error) {
	body, err := json.Marshal(facts)
	if err != nil {
		return nil, fmt.Errorf("normalizing facts: %w", err)
	}
	var normalized Facts
	if err := json.Unmarshal(body, &normalized); err != nil {
		return nil, fmt.Errorf("normalizing facts: %w", err)
	}
	return normalized, nil
}

// CanonicalJSON returns a deterministic JSON encoding of Facts. Callers
// should pass already-Normalize()'d Facts — see Normalize's doc comment for
// why a raw collector result isn't safe to hash directly.
func CanonicalJSON(facts Facts) ([]byte, error) {
	body, err := json.Marshal(facts)
	if err != nil {
		return nil, fmt.Errorf("canonicalizing facts: %w", err)
	}
	return body, nil
}

// Hash returns the BLAKE3 hex digest of the canonical encoding of facts —
// this is what the heartbeat's domain_hashes map carries
// (docs/compliance/04-PROTOCOL.md §3) and what the server compares against
// inventory_snapshots.content_hash to decide whether to request a resync.
func Hash(facts Facts) (string, error) {
	body, err := CanonicalJSON(facts)
	if err != nil {
		return "", err
	}
	sum := blake3.Sum256(body)
	return hex.EncodeToString(sum[:]), nil
}
