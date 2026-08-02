package scheduler

import (
	"context"
	"errors"
	"testing"
)

type fakeEntry struct {
	value    []byte
	revision uint64
}

func (e fakeEntry) Value() []byte    { return e.value }
func (e fakeEntry) Revision() uint64 { return e.revision }

// fakeKV is an in-memory KVStore for testing the leader election state
// machine without a real NATS server. failCreate/failUpdate let a test
// simulate another node winning the race.
type fakeKV struct {
	value      []byte
	revision   uint64
	exists     bool
	failCreate bool
	failUpdate bool
}

func (f *fakeKV) Get(ctx context.Context, key string) (KVEntry, error) {
	if !f.exists {
		return nil, ErrKeyNotFound
	}
	return fakeEntry{value: f.value, revision: f.revision}, nil
}

func (f *fakeKV) Create(ctx context.Context, key string, value []byte) (uint64, error) {
	if f.exists || f.failCreate {
		return 0, errors.New("key already exists")
	}
	f.exists = true
	f.value = value
	f.revision = 1
	return f.revision, nil
}

func (f *fakeKV) Update(ctx context.Context, key string, value []byte, revision uint64) (uint64, error) {
	if f.failUpdate || revision != f.revision {
		return 0, errors.New("revision mismatch")
	}
	f.value = value
	f.revision++
	return f.revision, nil
}

func TestLeaderElector_BecomesLeaderWhenKeyAbsent(t *testing.T) {
	kv := &fakeKV{}
	e := NewLeaderElector(kv, "node-a")

	if err := e.Tick(context.Background()); err != nil {
		t.Fatalf("Tick() error = %v", err)
	}
	if !e.IsLeader() {
		t.Error("IsLeader() = false, want true after winning an uncontested Create")
	}
}

func TestLeaderElector_RenewsLeadershipOnSubsequentTicks(t *testing.T) {
	kv := &fakeKV{}
	e := NewLeaderElector(kv, "node-a")

	for i := 0; i < 3; i++ {
		if err := e.Tick(context.Background()); err != nil {
			t.Fatalf("Tick() %d error = %v", i, err)
		}
	}
	if !e.IsLeader() {
		t.Error("IsLeader() = false after repeated renewals, want true")
	}
	if kv.revision != 3 {
		t.Errorf("revision = %d, want 3 (1 create + 2 renewals)", kv.revision)
	}
}

func TestLeaderElector_NotLeaderWhenSomeoneElseHoldsLease(t *testing.T) {
	kv := &fakeKV{exists: true, value: []byte("node-b"), revision: 5}
	e := NewLeaderElector(kv, "node-a")

	if err := e.Tick(context.Background()); err != nil {
		t.Fatalf("Tick() error = %v", err)
	}
	if e.IsLeader() {
		t.Error("IsLeader() = true, want false — node-b holds the lease")
	}
}

func TestLeaderElector_LosesRaceOnCreate(t *testing.T) {
	kv := &fakeKV{failCreate: true} // simulates another node's Create winning first
	e := NewLeaderElector(kv, "node-a")

	if err := e.Tick(context.Background()); err != nil {
		t.Fatalf("Tick() error = %v", err)
	}
	if e.IsLeader() {
		t.Error("IsLeader() = true, want false — lost the Create race")
	}
}

// TestLeaderElector_LosesLeaseIfUpdateRaced locks the exact scenario the
// revision-checked Update guards against: this node thought it was leader,
// but another node's Update won the race between our Get and our Update.
func TestLeaderElector_LosesLeaseIfUpdateRaced(t *testing.T) {
	kv := &fakeKV{exists: true, value: []byte("node-a"), revision: 1}
	e := NewLeaderElector(kv, "node-a")
	_ = e.Tick(context.Background())
	if !e.IsLeader() {
		t.Fatal("setup: expected to be leader before the race")
	}

	kv.failUpdate = true // simulate a concurrent Update stealing the revision
	if err := e.Tick(context.Background()); err != nil {
		t.Fatalf("Tick() error = %v", err)
	}
	if e.IsLeader() {
		t.Error("IsLeader() = true, want false after a raced Update")
	}
}

func TestLeaderElector_FailoverWhenLeaseExpires(t *testing.T) {
	kv := &fakeKV{} // empty bucket simulates the previous leader's key having expired
	a := NewLeaderElector(kv, "node-a")
	_ = a.Tick(context.Background())
	if !a.IsLeader() {
		t.Fatal("setup: node-a should have become leader")
	}

	// Simulate node-a's key expiring (TTL) by clearing the fake bucket,
	// then a second node contests it.
	kv.exists = false
	b := NewLeaderElector(kv, "node-b")
	if err := b.Tick(context.Background()); err != nil {
		t.Fatalf("Tick() error = %v", err)
	}
	if !b.IsLeader() {
		t.Error("IsLeader() = false, want true — node-b should take over after expiry")
	}
}
