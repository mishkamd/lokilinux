package eq

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestFlusher_TriggersOn100Events(t *testing.T) {
	q := NewQueue(1000)
	f := NewFlusher(q, 100, FlushMaxBytes, 10*time.Second) // interval far away — only count should fire

	var mu sync.Mutex
	var flushed [][]EventRecord
	send := func(recs []EventRecord) error {
		mu.Lock()
		flushed = append(flushed, recs)
		mu.Unlock()
		return nil
	}

	for i := 0; i < 150; i++ {
		q.Push(rec("e"), NORMAL)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	go f.Run(ctx, send)

	waitFor(t, 400*time.Millisecond, func() bool {
		mu.Lock()
		defer mu.Unlock()
		return len(flushed) >= 1 && len(flushed[0]) == 100
	})
}

func TestFlusher_On1Second(t *testing.T) {
	q := NewQueue(1000)
	f := NewFlusher(q, 100, FlushMaxBytes, 200*time.Millisecond) // short interval for test speed

	var mu sync.Mutex
	var flushed [][]EventRecord
	send := func(recs []EventRecord) error {
		mu.Lock()
		flushed = append(flushed, recs)
		mu.Unlock()
		return nil
	}

	q.Push(rec("only-one"), NORMAL) // far below the count trigger

	ctx, cancel := context.WithTimeout(context.Background(), 600*time.Millisecond)
	defer cancel()
	go f.Run(ctx, send)

	waitFor(t, 500*time.Millisecond, func() bool {
		mu.Lock()
		defer mu.Unlock()
		return len(flushed) >= 1
	})
}

func TestFlusher_TrimsBatchOverByteCap(t *testing.T) {
	q := NewQueue(1000)
	bigPayload := map[string]interface{}{"blob": strings.Repeat("x", 2000)}
	for i := 0; i < 10; i++ {
		r := rec("big")
		r.Payload = bigPayload
		q.Push(r, NORMAL)
	}

	// Cap small enough that gzip(10 records) exceeds it but gzip(fewer) does not.
	full, err := GzipJSON(q.Drain(10))
	if err != nil {
		t.Fatalf("GzipJSON: %v", err)
	}
	if len(full) == 0 {
		t.Fatal("expected non-empty gzip output")
	}

	q2 := NewQueue(1000)
	for i := 0; i < 10; i++ {
		r := rec("big")
		r.Payload = bigPayload
		q2.Push(r, NORMAL)
	}
	f := NewFlusher(q2, 10, len(full)/2, 10*time.Second)

	var mu sync.Mutex
	var flushed []EventRecord
	send := func(recs []EventRecord) error {
		mu.Lock()
		flushed = recs
		mu.Unlock()
		return nil
	}
	if !f.flushIfDue(send) {
		t.Fatal("expected flushIfDue to send something")
	}

	mu.Lock()
	defer mu.Unlock()
	if len(flushed) >= 10 {
		t.Fatalf("expected batch trimmed below full 10 records for a halved byte cap, got %d", len(flushed))
	}
	if len(flushed) == 0 {
		t.Fatal("expected at least 1 record to survive trimming")
	}
}

func waitFor(t *testing.T, timeout time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("condition not met within timeout")
}
