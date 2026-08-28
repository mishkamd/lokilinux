// Package eq implements a bounded, priority-aware event queue for the agent
// (Phase G2). It has no dependency on the gRPC generated types — the
// transport glue (agent/internal/agent/eventqueue.go) converts EventRecord
// to gen.EventRecord when flushing, keeping this package pure and testable
// in isolation.
package eq

import (
	"sort"
	"sync"
	"time"
)

// Priority classes, highest first. CRITICAL is never evicted to make room
// for anything else — see Queue.Push.
type Priority int

const (
	CRITICAL Priority = iota
	HIGH
	NORMAL
	LOW
)

// DefaultCapacity is the ring size when Config.Capacity is zero.
const DefaultCapacity = 10_000

// EventRecord is the queue's internal event shape — enough to batch and
// gzip later without any gRPC-generated type in this package.
type EventRecord struct {
	EventID       string
	Type          string
	Severity      string
	HostID        string
	Service       string
	Timestamp     time.Time
	Payload       map[string]interface{}
	PriorityClass Priority
}

type item struct {
	rec      EventRecord
	priority Priority
	seq      uint64
}

// Queue is a bounded, priority-ordered event buffer. Safe for concurrent use.
type Queue struct {
	mu       sync.Mutex
	items    []item
	capacity int
	nextSeq  uint64
	dropped  uint64
}

// NewQueue builds a Queue with the given capacity (DefaultCapacity if <= 0).
func NewQueue(capacity int) *Queue {
	if capacity <= 0 {
		capacity = DefaultCapacity
	}
	return &Queue{capacity: capacity, items: make([]item, 0, capacity)}
}

// Push adds rec at the given priority. If the queue is at capacity, it
// evicts the worst (lowest-priority, then oldest) non-CRITICAL item to make
// room. If every item currently queued is CRITICAL, the incoming record is
// dropped instead — CRITICAL entries are never evicted.
//
// ponytail: sustained CRITICAL volume exceeding capacity silently drops new
// CRITICAL events with no separate overflow signal beyond DroppedCount().
// Add a dedicated CRITICAL-overflow counter/alert if this is ever observed
// in practice — not built speculatively.
func (q *Queue) Push(rec EventRecord, priority Priority) (accepted bool) {
	q.mu.Lock()
	defer q.mu.Unlock()

	if len(q.items) >= q.capacity {
		evictIdx := -1
		for i, it := range q.items {
			if it.priority == CRITICAL {
				continue
			}
			if evictIdx == -1 || worse(it, q.items[evictIdx]) {
				evictIdx = i
			}
		}
		if evictIdx == -1 {
			q.dropped++
			return false
		}
		q.items = append(q.items[:evictIdx], q.items[evictIdx+1:]...)
	}

	q.items = append(q.items, item{rec: rec, priority: priority, seq: q.nextSeq})
	q.nextSeq++
	return true
}

// worse reports whether a is a better eviction candidate than b: lower
// priority (higher Priority value) first, oldest (lower seq) as tiebreak.
func worse(a, b item) bool {
	if a.priority != b.priority {
		return a.priority > b.priority
	}
	return a.seq < b.seq
}

// Drain removes and returns up to max queued records, highest priority
// first and oldest first within a priority tier.
func (q *Queue) Drain(max int) []EventRecord {
	q.mu.Lock()
	defer q.mu.Unlock()

	if max <= 0 || len(q.items) == 0 {
		return nil
	}

	order := make([]int, len(q.items))
	for i := range order {
		order[i] = i
	}
	items := q.items
	sort.Slice(order, func(i, j int) bool {
		a, b := items[order[i]], items[order[j]]
		if a.priority != b.priority {
			return a.priority < b.priority
		}
		return a.seq < b.seq
	})

	n := max
	if n > len(order) {
		n = len(order)
	}
	take := make(map[int]bool, n)
	out := make([]EventRecord, n)
	for i := 0; i < n; i++ {
		idx := order[i]
		out[i] = q.items[idx].rec
		take[idx] = true
	}

	remaining := q.items[:0]
	for i, it := range q.items {
		if !take[i] {
			remaining = append(remaining, it)
		}
	}
	q.items = remaining

	return out
}

// Len returns the number of records currently queued.
func (q *Queue) Len() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	return len(q.items)
}

// DroppedCount returns how many incoming records were dropped because the
// queue was saturated with CRITICAL entries.
func (q *Queue) DroppedCount() uint64 {
	q.mu.Lock()
	defer q.mu.Unlock()
	return q.dropped
}
