package policy

import (
	"fmt"
	"sync"
)

// Applier runs the STAGE → APPLY → HEALTH CHECK → COMMIT lifecycle.
//
// APPLY and HEALTH CHECK are callbacks injected from the Manager — the policy
// package owns the sequence, not the collector plumbing. A failed health
// check means the candidate is discarded BEFORE commit, so the last committed
// document stays active (plan §7: fail ⇒ ultima politică validă rămâne activă).
type Applier struct {
	store *Store

	mu sync.Mutex
}

func NewApplier(store *Store) *Applier {
	return &Applier{store: store}
}

// Apply hooks let the Manager wire BuildRegistry/heartbeat reconfiguration
// without an import cycle back into internal/agent.
type Hooks struct {
	// Apply transitions the running agent to the candidate document.
	Apply func(p *Policy) error
	// HealthCheck runs one full collection cycle against the new state.
	HealthCheck func() error
}

// Apply executes the guarded transition. On any error after Stage the
// candidate is dropped — no partial application, no rollback dance needed
// because nothing observable changed until Commit.
func (a *Applier) Apply(payload []byte, meta StoredMeta, hooks Hooks) (StoredMeta, error) {
	a.mu.Lock()
	defer a.mu.Unlock()

	staged, err := a.store.Stage(payload, meta)
	if err != nil {
		return StoredMeta{}, fmt.Errorf("stage: %w", err)
	}

	p, err := Parse(payload)
	if err != nil {
		return StoredMeta{}, fmt.Errorf("re-validate staged payload: %w", err)
	}

	if hooks.Apply == nil || hooks.HealthCheck == nil {
		return StoredMeta{}, fmt.Errorf("policy applier misconfigured: nil hooks")
	}
	if err := hooks.Apply(p); err != nil {
		return StoredMeta{}, fmt.Errorf("apply failed — last-good still active: %w", err)
	}
	if err := hooks.HealthCheck(); err != nil {
		// Candidate may have mutated runtime state; instruct caller to restore.
		return StoredMeta{}, fmt.Errorf("health check failed: %w", err)
	}

	if err := a.store.Commit(staged); err != nil {
		return StoredMeta{}, fmt.Errorf("commit: %w", err)
	}
	return staged.meta, nil
}
