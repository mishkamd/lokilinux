// Package hashing provides the canonical BLAKE3 hashing shared by the
// snapshot ingest path (verifying an agent's claimed content_hash) and the
// baseline resolver (hashing merged baseline state). Both need the exact
// same json.Marshal + BLAKE3 recipe — encoding/json sorts map keys, so the
// output is stable across runs and processes.
package hashing

import (
	"encoding/hex"
	"encoding/json"
	"fmt"

	"lukechampine.com/blake3"
)

// Canonical hashes a canonical fact/state document deterministically.
func Canonical(state map[string]any) (string, error) {
	body, err := json.Marshal(state)
	if err != nil {
		return "", fmt.Errorf("canonicalizing state: %w", err)
	}
	sum := blake3.Sum256(body)
	return hex.EncodeToString(sum[:]), nil
}
