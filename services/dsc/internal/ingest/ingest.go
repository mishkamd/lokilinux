// Package ingest processes one agent-reported resource-type snapshot:
// verify each resource's content hash -> store content-addressed ->
// insert a dsc_resource_states row per resource key. See
// docs/dsc/05-PROTOCOL.md for the wire shape this consumes (published to
// lokilinux.dsc.resource.snapshot.{resource_type} by the gRPC passthrough).
//
// Phase 1 scope (docs/dsc/13-MIGRATION.md §2): storage only. Diff against
// desired state, divergence detection, and promise evaluation
// (docs/dsc/03-PROMISE-ENGINE.md) are not implemented yet — every ingested
// resource is just recorded, not yet compared against anything.
package ingest

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"lukechampine.com/blake3"

	"github.com/lokilinux/dsc/internal/storage"
)

// permanentError marks a failure that can never succeed on retry — a bad
// content_hash, malformed JSON, an invalid agent_id. consumer.go Terms
// these instead of Nak-ing them, same non-negotiable policy
// services/compliance/internal/ingest documents (a bare Nak with no bound
// produced ~30k permanently-failing messages and pinned a CPU core for four
// days, the one time this was skipped).
type permanentError struct{ err error }

func (e *permanentError) Error() string { return e.err.Error() }
func (e *permanentError) Unwrap() error { return e.err }

func newPermanentError(format string, a ...any) error {
	return &permanentError{err: fmt.Errorf(format, a...)}
}

func isPermanent(err error) bool {
	var pe *permanentError
	return errors.As(err, &pe)
}

// ResourceSnapshot is the deserialized payload of one
// lokilinux.dsc.resource.snapshot.{resource_type} message.
type ResourceSnapshot struct {
	AgentID      uuid.UUID
	ResourceType string
	ContentHash  string                    // agent's claimed type-level (aggregate) hash — see Ingest's verification note
	FactsByKey   map[string]map[string]any // resource key -> canonical Attributes
}

// Result summarizes what Ingest did, for logging/metrics — never used for
// control flow by the caller.
type Result struct {
	ResourceType string
	KeysStored   int
}

// nativeResourceTypes are the DSC resource types with a native Provider
// (agent/internal/dsc/*_provider.go) — everything else in dsc.Registry is
// still collector_adapter.go's wrapper (docs/dsc/13-MIGRATION.md §4's
// per-domain promotion tracking). Grown by one entry per domain promoted;
// nothing else in the ingest path changes when a new entry lands here.
var nativeResourceTypes = map[string]bool{
	"package":          true,
	"sysctl":           true,
	"user":             true,
	"systemd_unit":     true,
	"audit_rule":       true,
	"repository":       true,
	"selinux_mode":     true,
	"certificate":      true,
	"cron_d_file":      true,
	"time_sync_config": true,
	"firewall_ruleset": true,
	"ssh_config":       true,
	"group":            true,
	"sudo_config":      true,
	"pam_config":       true,
	"login_defs":       true,
	"password_policy":  true,
	"file":             true,
}

func providerSourceFor(resourceType string) string {
	if nativeResourceTypes[resourceType] {
		return "native"
	}
	return "adapted"
}

// canonicalHash mirrors agent/internal/compliance/canonical.go's Hash
// function exactly (encoding/json + BLAKE3), same deliberate duplication
// services/compliance/internal/ingest.canonicalHash already documents —
// separate Go modules, no shared internal package, and this is only the
// second copy (agent, compliance) plus this one makes three; a fourth
// consumer is the actual extraction trigger, not before.
func canonicalHash(facts map[string]any) (string, error) {
	body, err := json.Marshal(facts)
	if err != nil {
		return "", fmt.Errorf("canonicalizing facts: %w", err)
	}
	sum := blake3.Sum256(body)
	return hex.EncodeToString(sum[:]), nil
}

// Ingester ties storage together for one resource-type snapshot.
type Ingester struct {
	store *storage.Store
}

func NewIngester(store *storage.Store) *Ingester {
	return &Ingester{store: store}
}

// Ingest verifies and stores every resource in one snapshot. Returns an
// error only for infrastructure failures or a verified hash mismatch — a
// snapshot whose claimed hash doesn't match its content is never stored,
// same reasoning services/compliance/internal/ingest.Ingest already applies
// (storing an unverifiable snapshot would poison anything read from it
// later).
func (in *Ingester) Ingest(ctx context.Context, snap ResourceSnapshot) (Result, error) {
	// An empty FactsByKey is a legitimate steady state, not a malformed
	// snapshot — a native provider returning zero resources this cycle
	// (e.g. password_policy_provider.go when pwquality.conf has no active
	// directives) is real, correct data on many hosts, not an error.
	// Falling through lets BatchWriteResourceKeys no-op on the empty write
	// set below and still reach UpsertProviderStatus, which is what settles
	// dsc_provider_status.content_hash — without that row,
	// diff_resource_hashes (dsc_ingest_service.py) never finds a match for
	// this agent/type and re-requests a full resync every heartbeat
	// forever, which is what was producing this exact permanent error,
	// logged at ERROR, every single heartbeat.
	//
	// ponytail: Phase 1's dsc.Registry is 100% adapted compliance.Collectors
	// (docs/dsc/02-PROVIDERS.md §2), each returning exactly one Resource —
	// so the type-level content_hash the agent claims is directly
	// verifiable against that single key's own recomputed hash. A
	// multi-resource native provider (Package, Phase 2+) needs full
	// aggregate-hash verification matching agent/internal/dsc.aggregateHash
	// — not implemented here since nothing exercises the multi-key path
	// yet; upgrade path is adding that check alongside the first provider
	// that actually returns more than one Resource per Collect() call.
	if len(snap.FactsByKey) == 1 {
		for _, facts := range snap.FactsByKey {
			recomputed, err := canonicalHash(facts)
			if err != nil {
				return Result{}, fmt.Errorf("hashing resource facts (%s/%s): %w", snap.AgentID, snap.ResourceType, err)
			}
			if recomputed != snap.ContentHash {
				return Result{}, newPermanentError(
					"resource snapshot %s/%s: claimed content_hash %s does not match recomputed %s",
					snap.AgentID, snap.ResourceType, snap.ContentHash, recomputed,
				)
			}
		}
	}

	providerSource := providerSourceFor(snap.ResourceType)

	writes := make([]storage.ResourceKeyWrite, 0, len(snap.FactsByKey))
	for key, facts := range snap.FactsByKey {
		body, err := json.Marshal(facts)
		if err != nil {
			return Result{}, fmt.Errorf("marshaling resource facts (%s/%s/%s): %w", snap.AgentID, snap.ResourceType, key, err)
		}
		sum := blake3.Sum256(body)
		writes = append(writes, storage.ResourceKeyWrite{
			Key:         key,
			ContentHash: hex.EncodeToString(sum[:]),
			Body:        body,
		})
	}
	if err := in.store.BatchWriteResourceKeys(ctx, snap.AgentID, snap.ResourceType, providerSource, writes); err != nil {
		return Result{}, err
	}
	stored := len(writes)

	// Migration-rollout tracking (docs/dsc/13-MIGRATION.md §4) — one row per
	// (agent, resource_type), not per key, so this runs once per snapshot
	// rather than once per stored resource.
	if err := in.store.UpsertProviderStatus(ctx, snap.AgentID, snap.ResourceType, providerSource, snap.ContentHash); err != nil {
		return Result{}, err
	}

	return Result{ResourceType: snap.ResourceType, KeysStored: stored}, nil
}
