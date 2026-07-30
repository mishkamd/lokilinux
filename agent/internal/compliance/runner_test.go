package compliance

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/lokilinux/agent/internal/storage"
)

var errFakeCollect = errors.New("boom")

type fakeCollector struct {
	domain   string
	interval time.Duration
	calls    int
	facts    Facts
	err      error
}

func (f *fakeCollector) Domain() string { return f.domain }

func (f *fakeCollector) Interval() time.Duration { return f.interval }

func (f *fakeCollector) Collect(ctx context.Context) (Facts, error) {
	f.calls++
	return f.facts, f.err
}

func newTestStore(t *testing.T) *storage.Store {
	t.Helper()
	store, err := storage.Open(filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatalf("opening test store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

func TestRunner_Tick_PopulatesHashesAndPersists(t *testing.T) {
	store := newTestStore(t)
	c := &fakeCollector{domain: "test_domain", facts: Facts{"key": "value"}}
	r := NewRunner([]Collector{c}, store, nil)

	r.tick(context.Background())

	hashes := r.Hashes()
	if hashes["test_domain"] == "" {
		t.Fatal("expected a hash for test_domain")
	}
	if c.calls != 1 {
		t.Errorf("Collect called %d times, want 1", c.calls)
	}

	result, ok := r.FullBody("test_domain")
	if !ok || result.Facts["key"] != "value" {
		t.Errorf("FullBody = %+v, ok=%v", result, ok)
	}

	// Persisted to SQLite — a fresh Runner backed by the same store should
	// recover the same hash without re-running the collector.
	r2 := NewRunner([]Collector{c}, store, nil)
	if err := r2.LoadState(context.Background()); err != nil {
		t.Fatalf("LoadState: %v", err)
	}
	if r2.Hashes()["test_domain"] != hashes["test_domain"] {
		t.Error("LoadState did not recover the persisted hash")
	}
}

func TestRunner_Tick_SkipsCollectorNotYetDue(t *testing.T) {
	c := &fakeCollector{domain: "slow_domain", interval: time.Hour, facts: Facts{"a": 1}}
	r := NewRunner([]Collector{c}, nil, nil)

	r.tick(context.Background())
	r.tick(context.Background())

	if c.calls != 1 {
		t.Errorf("Collect called %d times, want 1 (second tick within Interval())", c.calls)
	}
}

func TestRunner_Tick_CollectorErrorDoesNotBlockOthers(t *testing.T) {
	failing := &fakeCollector{domain: "broken", err: errFakeCollect}
	ok := &fakeCollector{domain: "fine", facts: Facts{"a": 1}}
	r := NewRunner([]Collector{failing, ok}, nil, nil)

	r.tick(context.Background())

	hashes := r.Hashes()
	if _, present := hashes["broken"]; present {
		t.Error("failing collector should not have produced a hash")
	}
	if hashes["fine"] == "" {
		t.Error("expected a hash for the collector that succeeded")
	}
}

func TestRunner_LoadState_NilStoreIsNoop(t *testing.T) {
	r := NewRunner(nil, nil, nil)
	if err := r.LoadState(context.Background()); err != nil {
		t.Errorf("LoadState with nil store returned error: %v", err)
	}
}
