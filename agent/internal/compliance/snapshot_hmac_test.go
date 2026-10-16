package compliance

import (
	"encoding/base64"
	"testing"
)

// The same vector is asserted in services/compliance/internal/ingest. If either
// side changes the signed string or the hash, this test or its twin fails.
func TestSnapshotMACVector(t *testing.T) {
	got := SnapshotMAC([]byte("0123456789abcdef0123456789abcdef"), "agent-1", "packages", "abc123")
	want := "0791b62895900c3f0687d0d0167514460c9797f3793f15c13e98f1b5a3978d87"
	if got != want {
		t.Fatalf("SnapshotMAC = %s, want %s", got, want)
	}
}

func TestSnapshotKeysInstallOnlyMovesForward(t *testing.T) {
	var keys SnapshotKeys
	k1 := SnapshotKey{KeyID: 1, Key: base64.StdEncoding.EncodeToString([]byte("k1"))}
	k2 := SnapshotKey{KeyID: 2, Key: base64.StdEncoding.EncodeToString([]byte("k2"))}

	if !keys.Install(k1) {
		t.Fatal("first key should install")
	}
	if !keys.Install(k2) {
		t.Fatal("newer key should install")
	}
	if keys.Install(k1) {
		t.Fatal("an older key must not roll the agent back")
	}
	if keys.CurrentKeyID() != 2 || keys.Previous == nil || keys.Previous.KeyID != 1 {
		t.Fatalf("after rotation current=%d previous=%+v", keys.CurrentKeyID(), keys.Previous)
	}
}

func TestMACForUsesCurrentKey(t *testing.T) {
	var keys SnapshotKeys
	keys.Install(SnapshotKey{KeyID: 7, Key: base64.StdEncoding.EncodeToString([]byte("0123456789abcdef0123456789abcdef"))})

	id, mac, err := keys.MACFor("agent-1", "packages", "abc123")
	if err != nil {
		t.Fatal(err)
	}
	if id != 7 || mac != "0791b62895900c3f0687d0d0167514460c9797f3793f15c13e98f1b5a3978d87" {
		t.Fatalf("MACFor = (%d, %s)", id, mac)
	}
}

func TestMACForWithoutKeyFails(t *testing.T) {
	var keys SnapshotKeys
	if _, _, err := keys.MACFor("agent-1", "packages", "abc123"); err == nil {
		t.Fatal("expected an error when no key was issued")
	}
}
