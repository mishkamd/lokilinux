package policy

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
)

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
