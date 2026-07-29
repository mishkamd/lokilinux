package compliance

import (
	"encoding/hex"
	"encoding/json"
	"fmt"

	"lukechampine.com/blake3"
)

// CanonicalJSON returns a deterministic JSON encoding of Facts.
//
// ponytail: encoding/json already sorts map[string]T keys alphabetically at
// every nesting level when marshaling — that's a documented guarantee of
// the stdlib encoder, not an accident — so no custom canonicalizer is
// needed here. Two Go processes marshaling the same Facts value always
// produce byte-identical output, which is exactly the property content-
// addressable storage and delta-sync (docs/compliance/04-PROTOCOL.md) need.
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
