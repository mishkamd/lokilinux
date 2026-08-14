package scheduler

import (
	"context"
	"log/slog"
	"time"

	"github.com/lokilinux/compliance/internal/storage"
)

// AssessmentClaimer is the subset of *storage.Store the poller needs to
// pick up the next queued assessment.
type AssessmentClaimer interface {
	ClaimNextPendingAssessment(ctx context.Context) (storage.Assessment, bool, error)
}

// AssessmentRunner is the subset of *ingest.Ingester the poller needs —
// narrow enough to fake in tests without a real evaluator/store.
type AssessmentRunner interface {
	RunAssessment(ctx context.Context, claimed storage.Assessment) error
}

// AssessmentPoller picks up PENDING compliance_assessments and runs them —
// leader-only, same reasoning as Dispatcher/Expirer: every replica racing
// to claim the same row would be wasteful (harmless since the claim is a
// single atomic UPDATE, but no reason for N replicas to all poll). One
// assessment runs at a time per tick — deliberately serial, not fanned out
// across goroutines, since an assessment already walks the whole matched
// fleet internally and Tick's own interval is the throttle a slow assessment
// needs (docs/compliance §24: never block on the whole fleet synchronously
// from an HTTP request, but a background poller work-stealing serially is
// exactly the async job model asked for).
type AssessmentPoller struct {
	leader LeadershipChecker
	claims AssessmentClaimer
	runner AssessmentRunner
	log    *slog.Logger
}

func NewAssessmentPoller(leader LeadershipChecker, claims AssessmentClaimer, runner AssessmentRunner, log *slog.Logger) *AssessmentPoller {
	return &AssessmentPoller{leader: leader, claims: claims, runner: runner, log: log}
}

// Tick claims and runs at most one assessment, doing nothing if this node
// isn't leader or nothing is queued. Returns true if an assessment ran.
func (p *AssessmentPoller) Tick(ctx context.Context) bool {
	if !p.leader.IsLeader() {
		return false
	}
	claimed, ok, err := p.claims.ClaimNextPendingAssessment(ctx)
	if err != nil {
		p.log.Error("failed to claim pending assessment", "error", err)
		return false
	}
	if !ok {
		return false
	}
	if err := p.runner.RunAssessment(ctx, claimed); err != nil {
		p.log.Error("assessment run failed", "assessment_id", claimed.ID, "error", err)
	}
	return true
}

// Run ticks on interval until ctx is cancelled.
func (p *AssessmentPoller) Run(ctx context.Context, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			p.Tick(ctx)
		}
	}
}
