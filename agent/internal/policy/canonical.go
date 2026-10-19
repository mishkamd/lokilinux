package policy

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
)

// CanonicalJSON is the byte form every integrity binding uses — sorted keys,
// compact separators, no HTML escaping. MUST stay identical to the backend's
// compiler.canonical_bytes and to agent/internal/security (job envelopes).
func CanonicalJSON(v interface{}) ([]byte, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return nil, fmt.Errorf("canonical marshal: %w", err)
	}
	return b, nil
}

// HashHex returns sha256 hex over canonical bytes.
func HashHex(canonical []byte) string {
	sum := sha256.Sum256(canonical)
	return hex.EncodeToString(sum[:])
}

// sha256Sum returns the raw sha256 digest of data.
func sha256Sum(data []byte) []byte {
	sum := sha256.Sum256(data)
	return sum[:]
}

// jsonMarshal/jsonUnmarshal small wrappers so store.go stays import-lean.
func jsonMarshal(v interface{}) []byte {
	b, _ := json.Marshal(v)
	return b
}

func jsonUnmarshal(data []byte, v interface{}) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	return dec.Decode(v)
}
