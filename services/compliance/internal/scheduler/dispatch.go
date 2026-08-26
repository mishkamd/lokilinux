package scheduler

import (
	"context"
	"log/slog"
	"time"
)

// LeadershipChecker is the subset of *LeaderElector the dispatcher needs —
// narrow enough that tests can fake "are we leader" without a real KVStore.
type LeadershipChecker interface {
	IsLeader() bool
}

// JobDispatcher is the subset of *storage.Store the dispatcher needs.
type JobDispatcher interface {
	DispatchScheduledJobs(ctx context.Context) (int64, error)
}

// Dispatcher periodically flips due SCHEDULED jobs to QUEUED — but only on
// the elected leader, so every replica doesn't race to UPDATE the same rows
// (harmless since the UPDATE is idempotent, but wasteful and log-noisy).
type Dispatcher struct {
	leader LeadershipChecker
	jobs   JobDispatcher
	log    *slog.Logger
}

func NewDispatcher(leader LeadershipChecker, jobs JobDispatcher, log *slog.Logger) *Dispatcher {
	return &Dispatcher{leader: leader, jobs: jobs, log: log}
}

// Tick runs one dispatch pass, doing nothing if this node isn't leader.
// Returns the number of jobs dispatched (0 if not leader or none were due).
func (d *Dispatcher) Tick(ctx context.Context) int64 {
	if !d.leader.IsLeader() {
		return 0
	}
	n, err := d.jobs.DispatchScheduledJobs(ctx)
	if err != nil {
		d.log.Error("failed to dispatch scheduled jobs", "error", err)
		return 0
	}
	if n > 0 {
		d.log.Info("dispatched scheduled jobs", "count", n)
	}
	return n
}

// Run ticks on interval until ctx is cancelled.
func (d *Dispatcher) Run(ctx context.Context, interval time.Duration) {
	loop(ctx, interval, func(ctx context.Context) { d.Tick(ctx) })
}
