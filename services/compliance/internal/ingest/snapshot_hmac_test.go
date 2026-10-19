package ingest

import (
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/lokilinux/compliance/internal/storage"
)

// Same vector as agent/internal/compliance/snapshot_hmac_test.go.
const vectorMAC = "0791b62895900c3f0687d0d0167514460c9797f3793f15c13e98f1b5a3978d87"

func vectorRecord() storage.SnapshotKeyRecord {
	return storage.SnapshotKeyRecord{
		Identity: "agent-1",
		Keys:     []storage.SnapshotKey{{KeyID: 7, Key: []byte("0123456789abcdef0123456789abcdef")}},
	}
}

func signedSnapshot(mac string, keyID int32) Snapshot {
	return Snapshot{
		AgentID:     uuid.New(),
		Domain:      "packages",
		ContentHash: "abc123",
		MAC:         mac,
		KeyID:       keyID,
	}
}

func TestSnapshotMACVector(t *testing.T) {
	if got := SnapshotMAC([]byte("0123456789abcdef0123456789abcdef"), "agent-1", "packages", "abc123"); got != vectorMAC {
		t.Fatalf("SnapshotMAC = %s, want %s", got, vectorMAC)
	}
}

func TestVerifyAcceptsCorrectMAC(t *testing.T) {
	if err := verifySnapshotMAC(vectorRecord(), signedSnapshot(vectorMAC, 7), true); err != nil {
		t.Fatalf("valid signature rejected: %v", err)
	}
}

func TestVerifyRejectsAlteredHash(t *testing.T) {
	snap := signedSnapshot(vectorMAC, 7)
	snap.ContentHash = "forged"
	if err := verifySnapshotMAC(vectorRecord(), snap, false); err == nil {
		t.Fatal("a MAC over a different hash must be rejected")
	}
}

func TestVerifyRejectsUnknownKeyID(t *testing.T) {
	if err := verifySnapshotMAC(vectorRecord(), signedSnapshot(vectorMAC, 99), false); err == nil {
		t.Fatal("a snapshot signed with an unknown key_id must be rejected")
	}
}

func TestUnsignedSnapshotAcceptedUnlessEnforced(t *testing.T) {
	unsigned := signedSnapshot("", 0)
	if err := verifySnapshotMAC(storage.SnapshotKeyRecord{}, unsigned, false); err != nil {
		t.Fatalf("unsigned snapshot should pass while enforcement is off: %v", err)
	}
	err := verifySnapshotMAC(storage.SnapshotKeyRecord{}, unsigned, true)
	if err == nil {
		t.Fatal("unsigned snapshot should be rejected when enforcement is on")
	}
	var pe *permanentError
	if !errors.As(err, &pe) {
		t.Fatalf("rejection should be permanent so JetStream does not redeliver it: %v", err)
	}
}
