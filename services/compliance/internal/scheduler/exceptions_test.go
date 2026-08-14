package scheduler

import (
	"context"
	"errors"
	"testing"
)

type fakeExceptionExpirer struct {
	expired int64
	err     error
	calls   int
}

func (f *fakeExceptionExpirer) ExpirePendingExceptions(ctx context.Context) (int64, error) {
	f.calls++
	return f.expired, f.err
}

func TestExpirer_Tick_SkipsWhenNotLeader(t *testing.T) {
	exceptions := &fakeExceptionExpirer{expired: 3}
	e := NewExpirer(fakeLeadership{leader: false}, exceptions, discardLogger())

	n := e.Tick(context.Background())
	if n != 0 {
		t.Errorf("Tick() = %d, want 0 (not leader)", n)
	}
	if exceptions.calls != 0 {
		t.Errorf("ExpirePendingExceptions called %d times, want 0 — a non-leader must never touch the table", exceptions.calls)
	}
}

func TestExpirer_Tick_ExpiresWhenLeader(t *testing.T) {
	exceptions := &fakeExceptionExpirer{expired: 2}
	e := NewExpirer(fakeLeadership{leader: true}, exceptions, discardLogger())

	n := e.Tick(context.Background())
	if n != 2 {
		t.Errorf("Tick() = %d, want 2", n)
	}
	if exceptions.calls != 1 {
		t.Errorf("ExpirePendingExceptions called %d times, want 1", exceptions.calls)
	}
}

func TestExpirer_Tick_ErrorReturnsZeroWithoutPanicking(t *testing.T) {
	exceptions := &fakeExceptionExpirer{err: errors.New("db unavailable")}
	e := NewExpirer(fakeLeadership{leader: true}, exceptions, discardLogger())

	n := e.Tick(context.Background())
	if n != 0 {
		t.Errorf("Tick() = %d, want 0 on error", n)
	}
}
