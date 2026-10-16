package compliance

import (
	"context"
	"encoding/json"
	"log/slog"
	"sync"
	"time"

	"github.com/lokilinux/agent/internal/storage"
)

// DomainResult is one collector's latest output.
type DomainResult struct {
	Domain string
	Facts  Facts
	Hash   string
}

// Runner ticks every registered collector on its own schedule and keeps the
// latest result per domain available for the heartbeat goroutine to read —
// deliberately its own goroutine, decoupled from sendHeartbeat
// (agent/internal/agent/manager.go), so an expensive collector (e.g.
// FileIntegrityCollector's /etc walk) never blocks or delays a heartbeat,
// per docs/compliance/03-AGENT-PLUGIN-SDK.md §3.
type Runner struct {
	registry []Collector
	store    *storage.Store // may be nil (tests, or a build with persistence disabled)
	log      *slog.Logger

	mu      sync.Mutex
	lastRun map[string]time.Time
	results map[string]DomainResult
}

func NewRunner(registry []Collector, store *storage.Store, log *slog.Logger) *Runner {
	return &Runner{
		registry: registry,
		store:    store,
		log:      log,
		lastRun:  map[string]time.Time{},
		results:  map[string]DomainResult{},
	}
}

// SetRegistry swaps the collector set at runtime — used by desired-state
// policy applies (internal/policy) to enable/disable collection domains
// without a restart. Swapping under mu keeps a concurrent tick from iterating
// the old slice mid-swap.
func (r *Runner) SetRegistry(registry []Collector) {
	r.mu.Lock()
	r.registry = registry
	r.mu.Unlock()
}

// LoadState warms the in-memory cache from the SQLite compliance_state
// table so a restart doesn't force a full domain_full resend for every
// domain — the agent picks up right where it left off, per
// docs/compliance/03-AGENT-PLUGIN-SDK.md §6. No-op if Runner was built
// without a store.
func (r *Runner) LoadState(ctx context.Context) error {
	if r.store == nil {
		return nil
	}
	states, err := r.store.AllComplianceState(ctx)
	if err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, st := range states {
		var facts Facts
		if st.Facts != "" {
			_ = json.Unmarshal([]byte(st.Facts), &facts)
		}
		r.lastRun[st.Domain] = st.LastRunAt
		r.results[st.Domain] = DomainResult{Domain: st.Domain, Facts: facts, Hash: st.LastHash}
	}
	return nil
}

// Run ticks every registered collector on a base interval, checking each
// collector's own Interval() to decide whether it's due. Blocks until ctx
// is cancelled — callers run this in its own goroutine.
func (r *Runner) Run(ctx context.Context, baseInterval time.Duration) {
	r.tick(ctx) // seed results immediately rather than waiting for the first tick
	ticker := time.NewTicker(baseInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			r.tick(ctx)
		}
	}
}

func (r *Runner) tick(ctx context.Context) {
	r.mu.Lock()
	registry := r.registry
	r.mu.Unlock()
	for _, c := range registry {
		domain := c.Domain()

		r.mu.Lock()
		last, ran := r.lastRun[domain]
		r.mu.Unlock()
		if ran && c.Interval() > 0 && time.Since(last) < c.Interval() {
			continue // not due yet
		}

		facts, err := c.Collect(ctx)
		if err != nil {
			if r.log != nil {
				r.log.Warn("compliance collector failed", "domain", domain, "error", err)
			}
			continue // one collector's failure never blocks the others
		}

		// Collapses any nested structs into map[string]any (see Normalize's
		// doc comment) so what gets hashed below is the same shape the
		// server reconstructs after its own JSON decode — hashing the raw
		// collector result made every struct-shaped domain fail the
		// server's verification, deterministically, forever.
		facts, err = Normalize(facts)
		if err != nil {
			if r.log != nil {
				r.log.Warn("compliance facts normalize failed", "domain", domain, "error", err)
			}
			continue
		}

		hash, err := Hash(facts)
		if err != nil {
			if r.log != nil {
				r.log.Warn("compliance collector hash failed", "domain", domain, "error", err)
			}
			continue
		}

		r.mu.Lock()
		r.lastRun[domain] = time.Now()
		r.results[domain] = DomainResult{Domain: domain, Facts: facts, Hash: hash}
		r.mu.Unlock()

		if r.store != nil {
			if factsJSON, err := CanonicalJSON(facts); err == nil {
				if err := r.store.UpsertComplianceState(ctx, domain, hash, string(factsJSON)); err != nil && r.log != nil {
					r.log.Warn("persisting compliance state failed", "domain", domain, "error", err)
				}
			}
		}
	}
}

// Hashes returns the latest domain->content-hash map for the heartbeat's
// domain_hashes field.
func (r *Runner) Hashes() map[string]string {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make(map[string]string, len(r.results))
	for domain, res := range r.results {
		out[domain] = res.Hash
	}
	return out
}

// FullBody returns the full Facts + hash for one domain, if collected yet —
// used to populate domain_full for domains the server flagged via
// resync_domains in the previous heartbeat's response.
func (r *Runner) FullBody(domain string) (DomainResult, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	res, ok := r.results[domain]
	return res, ok
}
