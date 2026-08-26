// Package scheduler runs the one primitive nothing in this codebase has
// today (docs/compliance/02-GO-SERVICE.md §4): scan cadence, maintenance
// windows, and Job.scheduled_time dispatch. Only the elected leader among
// replicas runs it — ingest scales independently of leadership.
package scheduler

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync/atomic"
	"time"
)

const leaderKey = "leader"

// KVEntry is the subset of jetstream.KeyValueEntry this package needs.
type KVEntry interface {
	Value() []byte
	Revision() uint64
}

// KVStore is the subset of jetstream.KeyValue this package needs — narrow
// enough to fake in tests, wide enough that the real jetstream.KeyValue
// (an interface itself) satisfies it structurally with no adapter needed.
type KVStore interface {
	Get(ctx context.Context, key string) (KVEntry, error)
	Create(ctx context.Context, key string, value []byte) (uint64, error)
	Update(ctx context.Context, key string, value []byte, revision uint64) (uint64, error)
}

// ErrKeyNotFound is what KVStore.Get returns for a missing key — defined
// here (not reusing jetstream.ErrKeyNotFound directly) so the fake used in
// unit tests doesn't need to import nats.go/jetstream at all.
var ErrKeyNotFound = errors.New("scheduler: leader key not found")

// LeaderElector holds (or contests) the leader lease. The underlying KV
// bucket must be created with a TTL (docs/compliance/02-GO-SERVICE.md §4) —
// leadership expires automatically if a leader stops renewing (crash,
// network partition), letting another replica take over without a manual
// failover step.
type LeaderElector struct {
	kv     KVStore
	nodeID string

	isLeader atomic.Bool
}

func NewLeaderElector(kv KVStore, nodeID string) *LeaderElector {
	return &LeaderElector{kv: kv, nodeID: nodeID}
}

// IsLeader reports whether this node held the lease as of the most recent
// Tick — safe to call from any goroutine.
func (e *LeaderElector) IsLeader() bool { return e.isLeader.Load() }

// Tick attempts to acquire or renew leadership once. Call it on a fixed
// interval well under the KV bucket's TTL (docs suggest TTL/3) so a
// slow tick or two doesn't lose the lease to a spurious expiry.
func (e *LeaderElector) Tick(ctx context.Context) error {
	entry, err := e.kv.Get(ctx, leaderKey)
	switch {
	case errors.Is(err, ErrKeyNotFound):
		// No leader currently holds the lease (first boot, or the previous
		// leader's key expired) — race to create it. Losing this race is
		// not an error, just means someone else is leader now.
		if _, createErr := e.kv.Create(ctx, leaderKey, []byte(e.nodeID)); createErr != nil {
			e.isLeader.Store(false)
			return nil
		}
		e.isLeader.Store(true)
		return nil

	case err != nil:
		return fmt.Errorf("getting leader key: %w", err)

	case string(entry.Value()) == e.nodeID:
		// We're the current leader — renew (refresh the TTL) using the
		// revision we just read, so a concurrent takeover after expiry
		// loses this race safely instead of silently overwriting it.
		if _, updateErr := e.kv.Update(ctx, leaderKey, []byte(e.nodeID), entry.Revision()); updateErr != nil {
			e.isLeader.Store(false) // lost the lease to someone else between Get and Update
			return nil
		}
		e.isLeader.Store(true)
		return nil

	default:
		// Someone else holds the lease.
		e.isLeader.Store(false)
		return nil
	}
}

// Run ticks on interval until ctx is cancelled. A failed tick is logged,
// never swallowed — a partitioned node that silently stops renewing would
// otherwise lose leadership with zero trace.
func (e *LeaderElector) Run(ctx context.Context, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	if err := e.Tick(ctx); err != nil { // attempt immediately on start, don't wait for the first tick
		slog.Warn("leader election tick failed", "node_id", e.nodeID, "error", err)
	}
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := e.Tick(ctx); err != nil {
				slog.Warn("leader election tick failed", "node_id", e.nodeID, "error", err)
			}
		}
	}
}
