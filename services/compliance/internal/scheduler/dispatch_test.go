package scheduler

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"
)

type fakeLeadership struct{ leader bool }

func (f fakeLeadership) IsLeader() bool { return f.leader }

type fakeJobDispatcher struct {
	dispatched int64
	err        error
	calls      int
}

func (f *fakeJobDispatcher) DispatchScheduledJobs(ctx context.Context) (int64, error) {
	f.calls++
	return f.dispatched, f.err
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func TestDispatcher_Tick_SkipsWhenNotLeader(t *testing.T) {
	jobs := &fakeJobDispatcher{dispatched: 3}
	d := NewDispatcher(fakeLeadership{leader: false}, jobs, discardLogger())

	n := d.Tick(context.Background())
	if n != 0 {
		t.Errorf("Tick() = %d, want 0 (not leader)", n)
	}
	if jobs.calls != 0 {
		t.Errorf("DispatchScheduledJobs called %d times, want 0 — a non-leader must never touch the jobs table", jobs.calls)
	}
}

func TestDispatcher_Tick_DispatchesWhenLeader(t *testing.T) {
	jobs := &fakeJobDispatcher{dispatched: 2}
	d := NewDispatcher(fakeLeadership{leader: true}, jobs, discardLogger())

	n := d.Tick(context.Background())
	if n != 2 {
		t.Errorf("Tick() = %d, want 2", n)
	}
	if jobs.calls != 1 {
		t.Errorf("DispatchScheduledJobs called %d times, want 1", jobs.calls)
	}
}

func TestDispatcher_Tick_ErrorReturnsZeroWithoutPanicking(t *testing.T) {
	jobs := &fakeJobDispatcher{err: errors.New("db unavailable")}
	d := NewDispatcher(fakeLeadership{leader: true}, jobs, discardLogger())

	n := d.Tick(context.Background())
	if n != 0 {
		t.Errorf("Tick() = %d, want 0 on error", n)
	}
}
