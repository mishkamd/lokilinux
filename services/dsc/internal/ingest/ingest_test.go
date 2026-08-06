package ingest

import (
	"context"
	"testing"

	"github.com/google/uuid"
)

// Empty FactsByKey is accepted (a provider legitimately collecting zero
// resources this cycle, e.g. password_policy_provider.go on a host with no
// active pwquality.conf directives) rather than rejected as malformed — see
// Ingest's doc comment. That accept path calls into storage
// (BatchWriteResourceKeys no-ops, UpsertProviderStatus still runs), so it
// isn't covered here: this package's unit tests, like
// TestIngest_RejectsMismatchedContentHash below, only exercise the
// pre-storage validation logic against a nil store.

func TestIngest_RejectsMismatchedContentHash(t *testing.T) {
	// Single-resource case: Ingest recomputes the one key's hash and compares
	// against the agent's claim before ever touching storage — a nil store
	// must never be dereferenced on this path.
	in := NewIngester(nil)
	_, err := in.Ingest(context.Background(), ResourceSnapshot{
		AgentID:      uuid.New(),
		ResourceType: "sshd",
		ContentHash:  "not-the-real-hash",
		FactsByKey:   map[string]map[string]any{"sshd": {"PermitRootLogin": "no"}},
	})
	if err == nil {
		t.Fatal("expected a content_hash mismatch error, got nil")
	}
	if !isPermanent(err) {
		t.Errorf("expected a permanent error (retrying won't fix a bad hash), got %v", err)
	}
}

func TestProviderSourceFor(t *testing.T) {
	cases := []struct {
		resourceType string
		want         string
	}{
		{"package", "native"},
		{"sysctl", "native"},
		{"sshd", "adapted"},
		{"unknown_future_domain", "adapted"},
	}
	for _, c := range cases {
		if got := providerSourceFor(c.resourceType); got != c.want {
			t.Errorf("providerSourceFor(%q) = %q, want %q", c.resourceType, got, c.want)
		}
	}
}

func TestCanonicalHash_Deterministic(t *testing.T) {
	facts := map[string]any{"PermitRootLogin": "no", "Port": float64(22)}
	h1, err := canonicalHash(facts)
	if err != nil {
		t.Fatalf("canonicalHash() error = %v", err)
	}
	h2, err := canonicalHash(facts)
	if err != nil {
		t.Fatalf("canonicalHash() error = %v", err)
	}
	if h1 != h2 {
		t.Errorf("canonicalHash() not deterministic: %s != %s", h1, h2)
	}
}
