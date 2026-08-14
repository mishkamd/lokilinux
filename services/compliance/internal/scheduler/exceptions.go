package scheduler

import (
	"context"
	"log/slog"
	"time"
)

// ExceptionExpirer is the subset of *storage.Store the expirer needs.
type ExceptionExpirer interface {
	ExpirePendingExceptions(ctx context.Context) (int64, error)
}

// Expirer periodically flips ACTIVE compliance_exceptions past their
// expires_at to EXPIRED (docs/compliance §17) — only on the elected leader,
// same reasoning as Dispatcher: the UPDATE is idempotent but no need for
// every replica to race it.
type Expirer struct {
	leader     LeadershipChecker
	exceptions ExceptionExpirer
	log        *slog.Logger
}

func NewExpirer(leader LeadershipChecker, exceptions ExceptionExpirer, log *slog.Logger) *Expirer {
	return &Expirer{leader: leader, exceptions: exceptions, log: log}
}

// Tick runs one expiry pass, doing nothing if this node isn't leader.
// Returns the number of exceptions expired.
func (e *Expirer) Tick(ctx context.Context) int64 {
	if !e.leader.IsLeader() {
		return 0
	}
	n, err := e.exceptions.ExpirePendingExceptions(ctx)
	if err != nil {
		e.log.Error("failed to expire compliance exceptions", "error", err)
		return 0
	}
	if n > 0 {
		e.log.Info("expired compliance exceptions", "count", n)
	}
	return n
}

// Run ticks on interval until ctx is cancelled.
func (e *Expirer) Run(ctx context.Context, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			e.Tick(ctx)
		}
	}
}
