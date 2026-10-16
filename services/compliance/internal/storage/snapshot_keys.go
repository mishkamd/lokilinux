package storage

import (
	"context"
	"encoding/base64"
	"fmt"

	"github.com/google/uuid"
)

// SnapshotKey is one signing key the backend issued to an agent.
type SnapshotKey struct {
	KeyID int32
	Key   []byte
}

// SnapshotKeyRecord is an agent's snapshot keys plus the identity string it
// signs with. The identity is agents.agent_id, not the primary key the NATS
// message carries, so the record has to be read from the agents row.
type SnapshotKeyRecord struct {
	Identity string
	Keys     []SnapshotKey
}

// SnapshotHMACKeys loads the current and previous snapshot key for the agent
// with this primary key (docs/security/SNAPSHOT_HMAC.md).
func (s *Store) SnapshotHMACKeys(ctx context.Context, agentPK uuid.UUID) (SnapshotKeyRecord, error) {
	var rec SnapshotKeyRecord
	var curEnc, prevEnc string
	var curID, prevID int32
	err := s.db.QueryRow(ctx, `
		SELECT agent_id,
		       COALESCE(snapshot_hmac_key, ''), COALESCE(snapshot_hmac_key_id, 0),
		       COALESCE(snapshot_hmac_prev_key, ''), COALESCE(snapshot_hmac_prev_key_id, 0)
		FROM agents WHERE id = $1
	`, agentPK).Scan(&rec.Identity, &curEnc, &curID, &prevEnc, &prevID)
	if err != nil {
		return SnapshotKeyRecord{}, fmt.Errorf("loading snapshot keys (%s): %w", agentPK, err)
	}

	for _, k := range []struct {
		enc string
		id  int32
	}{{curEnc, curID}, {prevEnc, prevID}} {
		if k.enc == "" || k.id == 0 {
			continue
		}
		raw, err := base64.StdEncoding.DecodeString(k.enc)
		if err != nil {
			return SnapshotKeyRecord{}, fmt.Errorf("decoding snapshot key %d (%s): %w", k.id, agentPK, err)
		}
		rec.Keys = append(rec.Keys, SnapshotKey{KeyID: k.id, Key: raw})
	}
	return rec, nil
}
