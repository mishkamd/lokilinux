package ingest

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"

	"github.com/lokilinux/compliance/internal/storage"
)

// SnapshotMAC mirrors agent/internal/compliance.SnapshotMAC. The signed string is
// "v1|agent_identity|domain|content_hash". Both packages carry the same vector
// test, so a change on one side fails the other.
func SnapshotMAC(key []byte, agentIdentity, domain, contentHash string) string {
	m := hmac.New(sha256.New, key)
	m.Write([]byte("v1|" + agentIdentity + "|" + domain + "|" + contentHash))
	return hex.EncodeToString(m.Sum(nil))
}

// verifySnapshotMAC checks the agent's signature on the snapshot's claimed hash.
// An unsigned snapshot passes unless enforce is set (ENFORCE_SNAPSHOT_HMAC).
//
// ponytail: the key is looked up per snapshot. Fine at current domain counts;
// cache by agent with a short TTL if this query shows up in profiles.
func verifySnapshotMAC(rec storage.SnapshotKeyRecord, snap Snapshot, enforce bool) error {
	if snap.MAC == "" {
		if enforce {
			return newPermanentError(
				"unsigned snapshot for agent=%s domain=%s rejected: ENFORCE_SNAPSHOT_HMAC is set",
				snap.AgentID, snap.Domain,
			)
		}
		return nil
	}
	for _, k := range rec.Keys {
		if k.KeyID != snap.KeyID {
			continue
		}
		want := SnapshotMAC(k.Key, rec.Identity, snap.Domain, snap.ContentHash)
		if !hmac.Equal([]byte(want), []byte(snap.MAC)) {
			return newPermanentError(
				"snapshot MAC mismatch for agent=%s domain=%s key_id=%d — rejecting",
				snap.AgentID, snap.Domain, snap.KeyID,
			)
		}
		return nil
	}
	return newPermanentError(
		"snapshot for agent=%s domain=%s signed with unknown key_id=%d — rejecting",
		snap.AgentID, snap.Domain, snap.KeyID,
	)
}
