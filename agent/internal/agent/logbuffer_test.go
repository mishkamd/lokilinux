package agent

import (
	"io"
	"log/slog"
	"testing"
	"time"
)

// TestLogRingBuffer_OnCritical_FiresForErrorLevel is the wiring test for
// Phase G2's proof-path producer: a log entry at Error level (or above)
// must invoke the onCritical callback with the formatted line, so
// NewManager's hookup into internal/eq.Queue actually receives events.
func TestLogRingBuffer_OnCritical_FiresForErrorLevel(t *testing.T) {
	inner := slog.NewTextHandler(io.Discard, nil)
	buf := NewLogRingBuffer(inner, 10)

	var gotLine string
	var calls int
	buf.SetOnCritical(func(line string, _ time.Time) {
		calls++
		gotLine = line
	})

	logger := slog.New(buf)
	logger.Error("disk full", "path", "/var")

	if calls != 1 {
		t.Fatalf("onCritical called %d times, want 1", calls)
	}
	if gotLine == "" {
		t.Fatal("onCritical received an empty line")
	}
}

// Below-error levels must never reach onCritical — only Info/Warn go
// through Lines()/Counts()' existing "informative" bucket.
func TestLogRingBuffer_OnCritical_SkipsInfoAndWarn(t *testing.T) {
	inner := slog.NewTextHandler(io.Discard, nil)
	buf := NewLogRingBuffer(inner, 10)

	var calls int
	buf.SetOnCritical(func(string, time.Time) { calls++ })

	logger := slog.New(buf)
	logger.Info("heartbeat sent")
	logger.Warn("retrying")

	if calls != 0 {
		t.Fatalf("onCritical called %d times for Info/Warn, want 0", calls)
	}
}

// No callback set (the default, cfg.EventQueue.Enabled=false case) must not
// panic — LogRingBuffer works standalone exactly as before Phase G2.
func TestLogRingBuffer_OnCritical_NilIsNoOp(t *testing.T) {
	inner := slog.NewTextHandler(io.Discard, nil)
	buf := NewLogRingBuffer(inner, 10)

	logger := slog.New(buf)
	logger.Error("boom")

	if _, _, critical := buf.Counts(); critical != 1 {
		t.Fatalf("Counts() critical = %d, want 1 (buffer itself still works with no callback)", critical)
	}
}
