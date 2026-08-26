package scheduler

import (
	"context"
	"time"
)

// loop is the shared ticker skeleton behind Dispatcher/Expirer/
// AssessmentPoller's Run methods — tick on interval until ctx is cancelled.
func loop(ctx context.Context, interval time.Duration, tick func(context.Context)) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			tick(ctx)
		}
	}
}
