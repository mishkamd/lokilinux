package eq

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"time"
)

// Flush trigger defaults (Phase G2 spec): 100 events, 256KB, or 1s,
// whichever comes first. All overridable via config.EventQueueConfig.
const (
	FlushMaxEvents = 100
	FlushMaxBytes  = 256 * 1024
	FlushInterval  = 1 * time.Second
)

// pollInterval is how often Run checks the count trigger between full
// Interval ticks — fine enough granularity to treat "100 events" as an
// early-flush trigger rather than only ever flushing on the 1s tick.
const pollInterval = 100 * time.Millisecond

// Flusher drains a Queue on a fixed cadence or when accumulated records hit
// a size/count trigger, whichever comes first, and hands the batch to send.
//
// ponytail: the byte trigger (MaxBytes) is enforced as a cap at flush time
// (trims the batch, see flushIfDue) rather than a separate early-wake
// signal — precise incremental byte accounting would need marshaling on
// every Push. Add a byte-driven early wake if bursty large-payload events
// make the count/interval triggers insufficient in practice.
type Flusher struct {
	Queue     *Queue
	MaxEvents int
	MaxBytes  int
	Interval  time.Duration
}

// NewFlusher builds a Flusher over q, filling zero-valued fields with the
// package defaults.
func NewFlusher(q *Queue, maxEvents, maxBytes int, interval time.Duration) *Flusher {
	if maxEvents <= 0 {
		maxEvents = FlushMaxEvents
	}
	if maxBytes <= 0 {
		maxBytes = FlushMaxBytes
	}
	if interval <= 0 {
		interval = FlushInterval
	}
	return &Flusher{Queue: q, MaxEvents: maxEvents, MaxBytes: maxBytes, Interval: interval}
}

// Run drains the queue and calls send whenever the count/byte/interval
// trigger fires, until ctx is cancelled. send errors are not retried here —
// the caller decides retry/backoff policy; a failed send's records are
// already gone from the queue (at-most-once from Run's perspective).
func (f *Flusher) Run(ctx context.Context, send func([]EventRecord) error) {
	poll := time.NewTicker(pollInterval)
	defer poll.Stop()

	lastFlush := time.Now()
	for {
		select {
		case <-ctx.Done():
			return
		case <-poll.C:
			due := f.Queue.Len() >= f.MaxEvents || time.Since(lastFlush) >= f.Interval
			if due && f.flushIfDue(send) {
				lastFlush = time.Now()
			}
		}
	}
}

// flushIfDue drains and sends whatever is queued; the byte trigger is
// honored by trimming the drained batch rather than a separate early-wake
// (see the Flusher ponytail comment). Returns whether anything was sent.
func (f *Flusher) flushIfDue(send func([]EventRecord) error) bool {
	if f.Queue.Len() == 0 {
		return false
	}
	records := f.Queue.Drain(f.MaxEvents)
	if len(records) == 0 {
		return false
	}
	// Enforce the byte cap by trimming the tail if the batch is oversized;
	// trimmed records are lost from this batch (they were already removed
	// from the queue by Drain) — acceptable since MaxBytes exists to bound
	// a single RPC payload, not to guarantee delivery of every trimmed tail.
	for {
		b, err := GzipJSON(records)
		if err != nil || len(b) <= f.MaxBytes || len(records) <= 1 {
			break
		}
		records = records[:len(records)-1]
	}
	_ = send(records)
	return true
}

// GzipJSON marshals records to JSON and gzips the result.
func GzipJSON(records []EventRecord) ([]byte, error) {
	raw, err := json.Marshal(records)
	if err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	gw := gzip.NewWriter(&buf)
	if _, err := gw.Write(raw); err != nil {
		return nil, err
	}
	if err := gw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}
