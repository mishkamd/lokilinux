package scheduler

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/lokilinux/compliance/internal/storage"
)

type fakeAssessmentClaimer struct {
	assessment storage.Assessment
	found      bool
	err        error
	calls      int
}

func (f *fakeAssessmentClaimer) ClaimNextPendingAssessment(ctx context.Context) (storage.Assessment, bool, error) {
	f.calls++
	return f.assessment, f.found, f.err
}

type fakeAssessmentRunner struct {
	err   error
	calls int
	got   storage.Assessment
}

func (f *fakeAssessmentRunner) RunAssessment(ctx context.Context, claimed storage.Assessment) error {
	f.calls++
	f.got = claimed
	return f.err
}

func TestAssessmentPoller_Tick_SkipsWhenNotLeader(t *testing.T) {
	claims := &fakeAssessmentClaimer{found: true}
	runner := &fakeAssessmentRunner{}
	p := NewAssessmentPoller(fakeLeadership{leader: false}, claims, runner, discardLogger())

	if ran := p.Tick(context.Background()); ran {
		t.Error("Tick() = true, want false (not leader)")
	}
	if claims.calls != 0 {
		t.Errorf("ClaimNextPendingAssessment called %d times, want 0 — a non-leader must never claim", claims.calls)
	}
}

func TestAssessmentPoller_Tick_NothingQueued(t *testing.T) {
	claims := &fakeAssessmentClaimer{found: false}
	runner := &fakeAssessmentRunner{}
	p := NewAssessmentPoller(fakeLeadership{leader: true}, claims, runner, discardLogger())

	if ran := p.Tick(context.Background()); ran {
		t.Error("Tick() = true, want false (nothing queued)")
	}
	if runner.calls != 0 {
		t.Errorf("RunAssessment called %d times, want 0", runner.calls)
	}
}

func TestAssessmentPoller_Tick_RunsClaimedAssessment(t *testing.T) {
	id := uuid.New()
	claims := &fakeAssessmentClaimer{found: true, assessment: storage.Assessment{ID: id}}
	runner := &fakeAssessmentRunner{}
	p := NewAssessmentPoller(fakeLeadership{leader: true}, claims, runner, discardLogger())

	if ran := p.Tick(context.Background()); !ran {
		t.Error("Tick() = false, want true (assessment was queued)")
	}
	if runner.calls != 1 {
		t.Errorf("RunAssessment called %d times, want 1", runner.calls)
	}
	if runner.got.ID != id {
		t.Errorf("RunAssessment got id %s, want %s", runner.got.ID, id)
	}
}

func TestAssessmentPoller_Tick_RunErrorDoesNotPanic(t *testing.T) {
	claims := &fakeAssessmentClaimer{found: true, assessment: storage.Assessment{ID: uuid.New()}}
	runner := &fakeAssessmentRunner{err: errors.New("evaluation failed")}
	p := NewAssessmentPoller(fakeLeadership{leader: true}, claims, runner, discardLogger())

	if ran := p.Tick(context.Background()); !ran {
		t.Error("Tick() = false, want true (still attempted the run)")
	}
}
