package agent

import (
	"context"
	"log/slog"
	"sync"
)

// logEntry is one buffered log record — enough to render a formatted line
// and classify it (connection event vs plain info vs critical).
type logEntry struct {
	line         string
	level        slog.Level
	isConnection bool
}

// LogRingBuffer wraps a slog.Handler and keeps the last N log entries in
// memory so they can be attached to outgoing heartbeats, both as formatted
// lines and as connection/informative/critical counts.
type LogRingBuffer struct {
	inner   slog.Handler
	mu      sync.Mutex
	entries []logEntry
	size    int
	next    int
	full    bool
}

func NewLogRingBuffer(inner slog.Handler, size int) *LogRingBuffer {
	return &LogRingBuffer{inner: inner, entries: make([]logEntry, size), size: size}
}

func (b *LogRingBuffer) Enabled(ctx context.Context, level slog.Level) bool {
	return b.inner.Enabled(ctx, level)
}

func (b *LogRingBuffer) Handle(ctx context.Context, r slog.Record) error {
	isConnection := false
	r.Attrs(func(a slog.Attr) bool {
		if a.Key == "event" && a.Value.String() == "connection" {
			isConnection = true
			return false
		}
		return true
	})

	entry := logEntry{
		line:         r.Time.Format("15:04:05") + " " + r.Level.String() + " " + r.Message,
		level:        r.Level,
		isConnection: isConnection,
	}

	b.mu.Lock()
	b.entries[b.next] = entry
	b.next = (b.next + 1) % b.size
	if b.next == 0 {
		b.full = true
	}
	b.mu.Unlock()
	return b.inner.Handle(ctx, r)
}

// ponytail: child handlers share the entries slice but get their own next/full
// cursor, so ring position can drift if a derived logger (.With/.WithGroup)
// writes concurrently with the parent. Not used anywhere in this agent today.
func (b *LogRingBuffer) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &LogRingBuffer{inner: b.inner.WithAttrs(attrs), entries: b.entries, size: b.size, next: b.next, full: b.full}
}

func (b *LogRingBuffer) WithGroup(name string) slog.Handler {
	return &LogRingBuffer{inner: b.inner.WithGroup(name), entries: b.entries, size: b.size, next: b.next, full: b.full}
}

func (b *LogRingBuffer) ordered() []logEntry {
	if !b.full {
		out := make([]logEntry, b.next)
		copy(out, b.entries[:b.next])
		return out
	}
	out := make([]logEntry, b.size)
	copy(out, b.entries[b.next:])
	copy(out[b.size-b.next:], b.entries[:b.next])
	return out
}

// Lines returns buffered log lines in chronological order.
func (b *LogRingBuffer) Lines() []string {
	b.mu.Lock()
	defer b.mu.Unlock()

	entries := b.ordered()
	out := make([]string, len(entries))
	for i, e := range entries {
		out[i] = e.line
	}
	return out
}

// Counts returns, over the currently buffered window: how many entries were
// tagged as connection events, how many were plain info/warn (informative,
// excluding connections already counted separately), and how many were
// error-level (critical).
func (b *LogRingBuffer) Counts() (connections, informative, critical int) {
	b.mu.Lock()
	defer b.mu.Unlock()

	for _, e := range b.ordered() {
		switch {
		case e.isConnection:
			connections++
		case e.level >= slog.LevelError:
			critical++
		default:
			informative++
		}
	}
	return connections, informative, critical
}
