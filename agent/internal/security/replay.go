package security

import (
	"context"
	"time"

	"github.com/lokilinux/agent/internal/storage"
)

// ReplayStore wraps the SQLite seen_jobs table with the retention policy
// implied by envelope lifetimes: entries must outlive the longest possible
// expires_at - issued_at window, plus clock-skew grace, before pruning.
type ReplayStore struct {
	store      *storage.Store
	retention  time.Duration
}

// DefaultRetention covers envelopes issued with up to 24h TTL (the platform
// signer issues 5-minute TTLs today; 25h leaves generous headroom) plus the
// 30s verification skew.
const DefaultRetention = 25 * time.Hour

func NewReplayStore(store *storage.Store) *ReplayStore {
	return &ReplayStore{store: store, retention: DefaultRetention}
}

// MarkSeen records nonce→job. Returns false when already seen (duplicate).
func (r *ReplayStore) MarkSeen(ctx context.Context, nonce, jobID string) (bool, error) {
	ok, err := r.store.MarkJobSeen(ctx, nonce, jobID)
	if err != nil {
		return false, err
	}
	// Opportunistic pruning piggybacks on inserts; failure to prune is
	// non-fatal (worst case: table grows, still correct).
	_ = r.store.PruneSeenJobs(ctx, time.Now().Add(-r.retention))
	return ok, nil
}
