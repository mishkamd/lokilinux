package compliance

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
)

// SnapshotKey is one HMAC key the server issued. Key is base64 of the raw key.
type SnapshotKey struct {
	KeyID int32  `json:"key_id"`
	Key   string `json:"key"`
}

// SnapshotKeys holds the current key and the one before it. The previous key
// stays valid for a while after rotation, so snapshots signed just before the
// switch still verify (docs/security/SNAPSHOT_HMAC.md, Rotation).
type SnapshotKeys struct {
	Current  *SnapshotKey `json:"current,omitempty"`
	Previous *SnapshotKey `json:"previous,omitempty"`
}

// CurrentKeyID is 0 when no key has been issued yet.
func (k *SnapshotKeys) CurrentKeyID() int32 {
	if k == nil || k.Current == nil {
		return 0
	}
	return k.Current.KeyID
}

// Install takes a key from the server. Only a higher key_id is accepted: an
// older key replayed by someone on the wire does not roll the agent back.
func (k *SnapshotKeys) Install(incoming SnapshotKey) bool {
	if incoming.KeyID <= 0 || incoming.Key == "" {
		return false
	}
	if k.Current != nil && incoming.KeyID <= k.Current.KeyID {
		return false
	}
	k.Previous = k.Current
	k.Current = &incoming
	return true
}

// SnapshotMAC is the HMAC-SHA256 that binds a domain's claimed content hash
// to this agent's key. The signed string is "v1|agent_id|domain|content_hash".
// content_hash is already canonical on both ends, so no JSON parity is needed.
func SnapshotMAC(key []byte, agentID, domain, contentHash string) string {
	m := hmac.New(sha256.New, key)
	m.Write([]byte("v1|" + agentID + "|" + domain + "|" + contentHash))
	return hex.EncodeToString(m.Sum(nil))
}

// MACFor computes the MAC with the current key. It returns the key_id used,
// so the receiver knows which key to check against.
func (k *SnapshotKeys) MACFor(agentID, domain, contentHash string) (int32, string, error) {
	if k == nil || k.Current == nil {
		return 0, "", fmt.Errorf("no snapshot HMAC key issued yet")
	}
	raw, err := base64.StdEncoding.DecodeString(k.Current.Key)
	if err != nil {
		return 0, "", fmt.Errorf("decoding snapshot HMAC key: %w", err)
	}
	return k.Current.KeyID, SnapshotMAC(raw, agentID, domain, contentHash), nil
}
