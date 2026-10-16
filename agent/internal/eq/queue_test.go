package eq

import "testing"

func rec(id string) EventRecord {
	return EventRecord{EventID: id, Type: "test.event", Severity: "INFO"}
}

func TestPush_NeverDropsCritical(t *testing.T) {
	q := NewQueue(3)
	for i := 0; i < 3; i++ {
		if !q.Push(rec("c"), CRITICAL) {
			t.Fatalf("push %d: expected accepted while queue not yet full", i)
		}
	}
	// Queue is now saturated with 3 CRITICAL items — a 4th CRITICAL must be
	// dropped, not evict an existing CRITICAL.
	if q.Push(rec("c4"), CRITICAL) {
		t.Fatal("expected 4th CRITICAL push to be dropped, not accepted")
	}
	if got := q.DroppedCount(); got != 1 {
		t.Fatalf("DroppedCount() = %d, want 1", got)
	}
	if got := q.Len(); got != 3 {
		t.Fatalf("Len() = %d, want 3 (no CRITICAL evicted)", got)
	}
}

func TestPush_DropsLowBeforeOlderNormal(t *testing.T) {
	q := NewQueue(2)
	if !q.Push(rec("normal-old"), NORMAL) {
		t.Fatal("expected first push accepted")
	}
	if !q.Push(rec("low"), LOW) {
		t.Fatal("expected second push accepted")
	}
	// Queue full (NORMAL, LOW). A new HIGH push must evict LOW (worse
	// priority), not the older NORMAL entry.
	if !q.Push(rec("high"), HIGH) {
		t.Fatal("expected HIGH push to be accepted via eviction")
	}
	drained := q.Drain(10)
	if len(drained) != 2 {
		t.Fatalf("Drain(10) returned %d records, want 2", len(drained))
	}
	if drained[0].EventID != "high" || drained[1].EventID != "normal-old" {
		t.Fatalf("Drain order = %v, want [high, normal-old] (LOW evicted, priority order preserved)",
			[]string{drained[0].EventID, drained[1].EventID})
	}
}

func TestDrain_OldestFirstWithinTier(t *testing.T) {
	q := NewQueue(10)
	q.Push(rec("first"), NORMAL)
	q.Push(rec("second"), NORMAL)
	q.Push(rec("third"), NORMAL)

	drained := q.Drain(10)
	if len(drained) != 3 {
		t.Fatalf("Drain(10) returned %d records, want 3", len(drained))
	}
	want := []string{"first", "second", "third"}
	for i, w := range want {
		if drained[i].EventID != w {
			t.Fatalf("drained[%d].EventID = %q, want %q", i, drained[i].EventID, w)
		}
	}
}

func TestDrain_RespectsMax(t *testing.T) {
	q := NewQueue(10)
	for i := 0; i < 5; i++ {
		q.Push(rec("x"), NORMAL)
	}
	drained := q.Drain(2)
	if len(drained) != 2 {
		t.Fatalf("Drain(2) returned %d records, want 2", len(drained))
	}
	if got := q.Len(); got != 3 {
		t.Fatalf("Len() after Drain(2) = %d, want 3 remaining", got)
	}
}
