package agent

import (
	"context"
	"testing"
)

func TestMaxParallelJobsDefault(t *testing.T) {
	if got := maxParallelJobs(0); got != defaultMaxParallelJobs {
		t.Fatalf("maxParallelJobs(0) = %d, want %d", got, defaultMaxParallelJobs)
	}
	if got := maxParallelJobs(5); got != 5 {
		t.Fatalf("maxParallelJobs(5) = %d, want 5", got)
	}
}

func TestAcquireJobSlotBlocksAtCapacity(t *testing.T) {
	slots := make(chan struct{}, 1)
	if !acquireJobSlot(context.Background(), slots) {
		t.Fatal("first slot should be free")
	}

	// The only slot is taken: a waiting job must give up once its ctx ends,
	// not run alongside the job that holds the slot.
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if acquireJobSlot(ctx, slots) {
		t.Fatal("acquire succeeded while the only slot was held")
	}

	<-slots // release
	if !acquireJobSlot(context.Background(), slots) {
		t.Fatal("slot should be free again after release")
	}
}
