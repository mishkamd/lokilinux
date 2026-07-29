// Package ingest processes one agent-reported domain snapshot end to end:
// verify -> store (content-addressable) -> evaluate applicable rules ->
// record verdicts. See docs/compliance/04-PROTOCOL.md for the wire shape
// this consumes (published to lokilinux.compliance.snapshot.{domain} by the
// gRPC passthrough) and docs/compliance/02-GO-SERVICE.md §2 for where this
// package sits in the service.
package ingest

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"lukechampine.com/blake3"

	"github.com/lokilinux/compliance/internal/drift"
	"github.com/lokilinux/compliance/internal/rules"
	"github.com/lokilinux/compliance/internal/storage"
)

// Snapshot is the deserialized payload of one
// lokilinux.compliance.snapshot.{domain} message.
type Snapshot struct {
	AgentID     uuid.UUID
	Domain      string
	ContentHash string         // claimed by the agent
	Facts       map[string]any // canonical fact document
}

// Result summarizes what Ingest did, for logging/metrics — never used for
// control flow by the caller.
type Result struct {
	SnapshotID     uuid.UUID
	Unchanged      bool // content_hash matched the latest known snapshot; still stored (immutable log) but nothing new to evaluate against
	RulesEvaluated int
	DriftDetected  bool
}

// canonicalHash mirrors agent/internal/compliance/canonical.go's Hash
// function exactly (encoding/json + BLAKE3) so a snapshot's claimed
// content_hash can be verified server-side. Deliberately duplicated rather
// than imported — the agent and this service are separate Go modules with
// no shared internal package today; if a third consumer ever needs the
// same hashing, that's the point to extract a shared module, not before.
func canonicalHash(facts map[string]any) (string, error) {
	body, err := json.Marshal(facts)
	if err != nil {
		return "", fmt.Errorf("canonicalizing facts: %w", err)
	}
	sum := blake3.Sum256(body)
	return hex.EncodeToString(sum[:]), nil
}

// Ingester ties storage and rule evaluation together for one snapshot.
type Ingester struct {
	store     *storage.Store
	evaluator rules.Evaluator
}

func NewIngester(store *storage.Store, evaluator rules.Evaluator) *Ingester {
	return &Ingester{store: store, evaluator: evaluator}
}

// Ingest verifies, stores, and evaluates one snapshot. Returns an error
// only for infrastructure failures (DB unreachable, etc.) — a hash
// mismatch is reported as an error too, since storing an unverifiable
// snapshot would poison drift detection and scoring for this agent/domain
// going forward.
func (in *Ingester) Ingest(ctx context.Context, snap Snapshot) (Result, error) {
	body, err := json.Marshal(snap.Facts)
	if err != nil {
		return Result{}, fmt.Errorf("marshaling snapshot facts: %w", err)
	}

	computedHash, err := canonicalHash(snap.Facts)
	if err != nil {
		return Result{}, err
	}
	if computedHash != snap.ContentHash {
		return Result{}, fmt.Errorf(
			"content_hash mismatch for agent=%s domain=%s: agent claimed %s, computed %s — rejecting",
			snap.AgentID, snap.Domain, snap.ContentHash, computedHash,
		)
	}

	previousHash, hadPrevious, err := in.store.LatestSnapshotHash(ctx, snap.AgentID, snap.Domain)
	if err != nil {
		return Result{}, err
	}
	unchanged := hadPrevious && previousHash == computedHash

	// Fetch the previous domain body *before* overwriting anything — this is
	// the "vs previous snapshot" comparison from docs/compliance/08-DRIFT-FIM.md §1.
	// ("vs baseline" needs baseline_effective, which nothing populates yet —
	// see storage.ActiveRulesForDomain's ponytail note for the same honest gap.)
	var driftDetected bool
	if hadPrevious && !unchanged {
		driftDetected, err = in.detectDrift(ctx, snap, previousHash)
		if err != nil {
			return Result{}, err
		}
	}

	if err := in.store.UpsertInventoryBlob(ctx, computedHash, body, "blake3"); err != nil {
		return Result{}, err
	}
	snapshotID, err := in.store.InsertInventorySnapshot(ctx, snap.AgentID, snap.Domain, computedHash)
	if err != nil {
		return Result{}, err
	}

	evaluated, err := in.evaluateRules(ctx, snap)
	if err != nil {
		return Result{}, err
	}

	return Result{SnapshotID: snapshotID, Unchanged: unchanged, RulesEvaluated: evaluated, DriftDetected: driftDetected}, nil
}

// detectDrift compares the new facts against the previous snapshot's
// decoded body and, if they differ structurally, records a drift_events row.
func (in *Ingester) detectDrift(ctx context.Context, snap Snapshot, previousHash string) (bool, error) {
	previousBody, err := in.store.GetBlobBody(ctx, previousHash)
	if err != nil {
		return false, err
	}
	var previousFacts map[string]any
	if err := json.Unmarshal(previousBody, &previousFacts); err != nil {
		return false, fmt.Errorf("decoding previous snapshot body for drift comparison: %w", err)
	}

	event := drift.Detect(snap.Domain, drift.ComparedAgainstPreviousSnapshot, previousFacts, snap.Facts)
	if event == nil {
		return false, nil
	}

	fieldDiffs := make([]storage.DriftFieldDiff, 0, len(event.FieldDiffs))
	for _, d := range event.FieldDiffs {
		oldJSON, _ := json.Marshal(d.OldValue)
		newJSON, _ := json.Marshal(d.NewValue)
		fieldDiffs = append(fieldDiffs, storage.DriftFieldDiff{FieldPath: d.FieldPath, OldValue: oldJSON, NewValue: newJSON})
	}

	_, err = in.store.InsertDriftEvent(
		ctx, snap.AgentID, event.Domain, string(event.ComparedAgainst),
		string(event.Severity), string(event.ChangeType), event.Summary, fieldDiffs,
	)
	if err != nil {
		return false, err
	}
	return true, nil
}

func (in *Ingester) evaluateRules(ctx context.Context, snap Snapshot) (int, error) {
	activeRules, err := in.store.ActiveRulesForDomain(ctx, snap.Domain)
	if err != nil {
		return 0, err
	}

	for _, r := range activeRules {
		verdict := in.evaluator.Evaluate(ctx, r.Rule, snap.Facts)

		var actualValueJSON, evidenceJSON []byte
		if verdict.ActualValue != nil {
			actualValueJSON, _ = json.Marshal(verdict.ActualValue)
		}
		if verdict.Evidence != nil {
			evidenceJSON, _ = json.Marshal(verdict.Evidence)
		}
		errMsg := ""
		if verdict.Err != nil {
			errMsg = verdict.Err.Error()
		}

		ruleID, err := uuid.Parse(r.Rule.ID)
		if err != nil {
			return len(activeRules), fmt.Errorf("rule %s has a non-UUID ID %q: %w", r.RuleKey, r.Rule.ID, err)
		}

		if err := in.store.InsertRuleEvaluation(
			ctx, snap.AgentID, ruleID, r.PolicySetID,
			string(verdict.Result), actualValueJSON, evidenceJSON, errMsg,
		); err != nil {
			return len(activeRules), err
		}
	}

	return len(activeRules), nil
}
