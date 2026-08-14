// Package baseline computes the effective baseline for an agent by merging
// every published baseline whose scope selector matches the agent's
// attributes, most-specific wins per key (docs/compliance/06-BASELINE.md §1-2).
package baseline

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"

	"github.com/google/uuid"
	"lukechampine.com/blake3"

	"github.com/lokilinux/compliance/internal/scope"
	"github.com/lokilinux/compliance/internal/storage"
)

// scopeRank orders scope_type by specificity: GLOBAL < OS < ROLE <
// ENVIRONMENT < DATACENTER < CLUSTER < APPLICATION (06-BASELINE.md §1).
// Merge order is derived purely from this rank plus whether the selector
// matches — parent_baseline_id is UI breadcrumbing, never merge order.
var scopeRank = map[string]int{
	"GLOBAL":      0,
	"OS":          1,
	"ROLE":        2,
	"ENVIRONMENT": 3,
	"DATACENTER":  4,
	"CLUSTER":     5,
	"APPLICATION": 6,
}

// Effective is the resolved effective baseline for one agent.
type Effective struct {
	AgentID            uuid.UUID
	BaselineVersionIDs []uuid.UUID // ordered GLOBAL -> ... -> APPLICATION
	MergedState        map[string]any
	MergedHash         string
}

// Resolver computes effective baselines. It is stateless apart from the
// store: Resolve is a pure function of (agent attributes, published
// baseline versions), so baseline_effective is a materialized cache, not a
// source of truth (06-BASELINE.md §2) — safe to recompute at any time.
type Resolver struct {
	store *storage.Store
}

func NewResolver(store *storage.Store) *Resolver {
	return &Resolver{store: store}
}

// Resolve merges every published baseline whose selector matches the agent
// and returns the effective state — without writing anything. MergedState
// is never nil: an agent with no matching baseline gets an empty state so
// callers have a deterministic answer instead of a nil-map special case.
func (r *Resolver) Resolve(ctx context.Context, agentID uuid.UUID) (Effective, error) {
	attrs, err := r.store.LoadAgentAttributes(ctx, agentID)
	if err != nil {
		return Effective{}, err
	}

	published, err := r.store.LoadPublishedBaselines(ctx)
	if err != nil {
		return Effective{}, err
	}

	eff := mergeForAgent(agentID, attrs, published)
	hash, err := canonicalHash(eff.MergedState)
	if err != nil {
		return Effective{}, fmt.Errorf("hashing merged baseline state: %w", err)
	}
	eff.MergedHash = hash
	return eff, nil
}

// mergeForAgent is the pure half of Resolve — selector matching, specificity
// sorting, and deep merge — split out so the merge algorithm is unit-testable
// without a database. mergeForAgent never returns a nil MergedState.
func mergeForAgent(agentID uuid.UUID, attrs storage.AgentAttributes, published []storage.PublishedBaseline) Effective {
	matching := make([]storage.PublishedBaseline, 0, len(published))
	for _, p := range published {
		if selectorMatches(p.ScopeSelector, attrs) {
			matching = append(matching, p)
		}
	}
	if len(matching) == 0 {
		return Effective{AgentID: agentID, MergedState: map[string]any{}}
	}

	sort.SliceStable(matching, func(i, j int) bool {
		return scopeRank[matching[i].ScopeType] < scopeRank[matching[j].ScopeType]
	})

	merged := map[string]any{}
	versionIDs := make([]uuid.UUID, 0, len(matching))
	for _, p := range matching {
		deepMergeOverwrite(merged, p.ExpectedState)
		versionIDs = append(versionIDs, p.VersionID)
	}
	return Effective{
		AgentID:            agentID,
		BaselineVersionIDs: versionIDs,
		MergedState:        merged,
	}
}

// RecomputeAll resolves and materializes baseline_effective for every
// agent — the handler for COMPLIANCE_BASELINE_PUBLISHED (fleet-wide
// invalidation, 06-BASELINE.md §2). Agents with no matching baseline get
// an empty merged_state so the drift path has a deterministic "covered by
// an empty baseline, no deviation" answer instead of a missing row.
// Returns the number of agents materialized.
func (r *Resolver) RecomputeAll(ctx context.Context) (int, error) {
	agentIDs, err := r.store.ListAgentIDs(ctx)
	if err != nil {
		return 0, err
	}
	for _, id := range agentIDs {
		eff, err := r.Resolve(ctx, id)
		if err != nil {
			return 0, fmt.Errorf("resolving baseline for agent %s: %w", id, err)
		}
		if err := r.store.UpsertBaselineEffective(ctx, id, eff.BaselineVersionIDs, eff.MergedState, eff.MergedHash); err != nil {
			return 0, err
		}
	}
	return len(agentIDs), nil
}

// ReconcileOnStartup recomputes baseline_effective for every agent that
// lacks a row, but ONLY when at least one published baseline exists.
// Called from main.go on startup so baseline_effective rows survive
// service restarts (restart loses the NATS message backlog so the
// COMPLIANCE_BASELINE_PUBLISHED consumer would never re-trigger).
func (r *Resolver) ReconcileOnStartup(ctx context.Context) error {
	baselines, err := r.store.LoadPublishedBaselines(ctx)
	if err != nil {
		return err
	}
	if len(baselines) == 0 {
		return nil // no baselines published yet — nothing to reconcile
	}
	agentIDs, err := r.store.ListAgentIDs(ctx)
	if err != nil {
		return err
	}
	for _, id := range agentIDs {
		_, found, err := r.store.GetBaselineEffective(ctx, id)
		if err != nil {
			return err
		}
		if found {
			continue // already has a row
		}
		eff, err := r.Resolve(ctx, id)
		if err != nil {
			return err
		}
		if err := r.store.UpsertBaselineEffective(ctx, id, eff.BaselineVersionIDs, eff.MergedState, eff.MergedHash); err != nil {
			return err
		}
	}
	return nil
}

// selectorMatches evaluates a scope_selector against an agent's attributes.
// Thin forwarder to scope.Matches (internal/scope/selector.go) — the actual
// matching rule is shared with policy set resolution (internal/policy) and
// lives there once; kept as a same-named wrapper here so this package's
// existing tests (resolver_test.go) needed no changes.
func selectorMatches(selector map[string]any, attrs storage.AgentAttributes) bool {
	return scope.Matches(selector, scope.AgentAttributes{
		OsDistro: attrs.OsDistro, OsVersion: attrs.OsVersion,
		Category: attrs.Category, Project: attrs.Project,
	})
}

// deepMergeOverwrite merges src into dst per-key, recursing into nested
// objects — an APPLICATION-scope baseline overriding only
// sshd.PermitRootLogin does not blow away the OS-scope baseline's whole
// sshd domain, just that key (06-BASELINE.md §2). Later (more specific)
// scopes win.
func deepMergeOverwrite(dst, src map[string]any) {
	for k, sv := range src {
		if sm, ok := sv.(map[string]any); ok {
			dm, ok := dst[k].(map[string]any)
			if !ok {
				dm = map[string]any{}
				dst[k] = dm
			}
			deepMergeOverwrite(dm, sm)
			continue
		}
		dst[k] = sv
	}
}

// canonicalHash hashes the merged state deterministically: encoding/json
// sorts map keys, so the output is stable across runs and processes.
// BLAKE3 matches the agent collectors' canonical hashing choice
// (04-PROTOCOL.md §1, 06-BASELINE.md §3).
func canonicalHash(state map[string]any) (string, error) {
	body, err := json.Marshal(state)
	if err != nil {
		return "", fmt.Errorf("canonicalizing merged baseline state: %w", err)
	}
	sum := blake3.Sum256(body)
	return hex.EncodeToString(sum[:]), nil
}
