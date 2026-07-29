package compliance

import "testing"

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
