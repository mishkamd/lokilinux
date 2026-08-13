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
	"errors"
	"fmt"
	"slices"

	"github.com/google/uuid"
	"lukechampine.com/blake3"

	"github.com/lokilinux/compliance/internal/drift"
	"github.com/lokilinux/compliance/internal/policy"
	"github.com/lokilinux/compliance/internal/rules"
	"github.com/lokilinux/compliance/internal/scope"
	"github.com/lokilinux/compliance/internal/scoring"
	"github.com/lokilinux/compliance/internal/storage"
)

// permanentError marks a failure that can never succeed on retry — a bad
// content_hash, malformed JSON, an invalid agent_id. consumer.go Terms
// these instead of Nak-ing them: retrying is pure waste, and without a
// bound it's an infinite redelivery loop. Confirmed live — this exact class
// of error (struct-shaped domains hashing differently server-side, see
// agent/internal/compliance/canonical.go's Normalize) pinned a CPU core for
// four days across ~30k permanently-failing messages, none of which could
// ever have succeeded no matter how many times they were redelivered.
type permanentError struct{ err error }

func (e *permanentError) Error() string { return e.err.Error() }
func (e *permanentError) Unwrap() error { return e.err }

func newPermanentError(format string, a ...any) error {
	return &permanentError{err: fmt.Errorf(format, a...)}
}

// isPermanent reports whether err (or anything it wraps) is a permanentError.
func isPermanent(err error) bool {
	var pe *permanentError
	return errors.As(err, &pe)
}

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
		return Result{}, newPermanentError(
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

	// "vs baseline" comparison (08-DRIFT-FIM.md §1) — independent of whether
	// the state changed since the previous snapshot: a deviation from the
	// effective baseline is reportable even on the very first snapshot, and
	// is recorded once per distinct diff state, not once per heartbeat.
	baselineDrift, err := in.detectBaselineDrift(ctx, snap)
	if err != nil {
		return Result{}, err
	}
	driftDetected = driftDetected || baselineDrift

	evaluated, err := in.evaluateRules(ctx, snap)
	if err != nil {
		return Result{}, err
	}
	if evaluated > 0 {
		if err := in.updateComplianceScores(ctx, snap.AgentID); err != nil {
			return Result{}, err
		}
	}

	if snap.Domain == "file_integrity" && !unchanged {
		if err := in.ingestFileIntegrity(ctx, snap); err != nil {
			return Result{}, err
		}
	}

	return Result{SnapshotID: snapshotID, Unchanged: unchanged, RulesEvaluated: evaluated, DriftDetected: driftDetected}, nil
}

// ingestFileIntegrity is the per-file breakdown that rides alongside the
// generic snapshot/drift path above (never instead of it — the generic path
// still gives file_integrity an audit-trail blob and a domain-level drift
// event like every other domain). This is what actually populates
// file_hashes/file_changes (migration 017), which nothing wrote to before
// this — the generic inventory_snapshots pipeline has no concept of "one
// row per file," only "one blob per domain."
func (in *Ingester) ingestFileIntegrity(ctx context.Context, snap Snapshot) error {
	existing, err := in.store.ExistingFileHashes(ctx, snap.AgentID)
	if err != nil {
		return fmt.Errorf("loading existing file hashes: %w", err)
	}

	current := parseAgentFileHashes(snap.Facts)
	changes := diffFileIntegrity(existing, current)

	ignorePatterns, err := in.store.LoadFileIntegrityIgnorePatterns(ctx)
	if err != nil {
		return err
	}
	changes = filterIgnored(changes, ignorePatterns)

	changedPaths := make([]string, 0, len(changes))
	for _, c := range changes {
		if err := in.store.InsertFileChange(ctx, snap.AgentID, c.Path, c.OldHash, c.NewHash, c.ChangeKind); err != nil {
			return err
		}
		if c.ChangeKind == "DELETED" {
			if err := in.store.DeleteFileHash(ctx, snap.AgentID, c.Path); err != nil {
				return err
			}
		} else if err := in.store.UpsertFileHash(ctx, snap.AgentID, c.Path, "blake3", c.NewHash, c.NewSize); err != nil {
			return err
		}
		changedPaths = append(changedPaths, c.Path)
	}

	// Correlation with the compliance engine (docs/compliance §12): a
	// monitored config file changing off-cycle re-evaluates exactly the
	// rules that depend on it, rather than waiting for that domain's next
	// scheduled snapshot.
	return in.reevaluateAffectedRules(ctx, snap.AgentID, changedPaths)
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

// detectBaselineDrift compares the new facts against the agent's effective
// baseline (docs/compliance/08-DRIFT-FIM.md §1, the BASELINE comparison) and
// records a drift_events row when they deviate. A persisted deviation is
// recorded once per distinct diff state: the same set of changed field
// paths as the most recent BASELINE event for this agent/domain does not
// spam a new event every heartbeat.
func (in *Ingester) detectBaselineDrift(ctx context.Context, snap Snapshot) (bool, error) {
	mergedState, found, err := in.store.GetBaselineEffective(ctx, snap.AgentID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}
	rawBaseline, ok := mergedState[snap.Domain]
	if !ok {
		return false, nil // effective baseline doesn't cover this domain
	}
	baselineFacts, ok := rawBaseline.(map[string]any)
	if !ok {
		return false, nil // domain value isn't an object — nothing to diff
	}

	event := drift.Detect(snap.Domain, drift.ComparedAgainstBaseline, baselineFacts, snap.Facts)
	if event == nil {
		return false, nil
	}

	paths := baselineDriftFieldPaths(event.FieldDiffs)
	existing, have, err := in.store.LatestBaselineDriftFieldPaths(ctx, snap.AgentID, snap.Domain)
	if err != nil {
		return false, err
	}
	if have && slices.Equal(existing, paths) {
		return false, nil // same deviation already recorded — state hasn't changed further
	}

	fieldDiffs := make([]storage.DriftFieldDiff, 0, len(event.FieldDiffs))
	for _, d := range event.FieldDiffs {
		oldJSON, _ := json.Marshal(d.OldValue)
		newJSON, _ := json.Marshal(d.NewValue)
		fieldDiffs = append(fieldDiffs, storage.DriftFieldDiff{FieldPath: d.FieldPath, OldValue: oldJSON, NewValue: newJSON})
	}
	if _, err := in.store.InsertDriftEvent(
		ctx, snap.AgentID, event.Domain, string(event.ComparedAgainst),
		string(event.Severity), string(event.ChangeType), event.Summary, fieldDiffs,
	); err != nil {
		return false, err
	}
	return true, nil
}

// baselineDriftFieldPaths extracts the field paths of a drift diff, sorted,
// so identical deviation states compare equal regardless of walk order.
func baselineDriftFieldPaths(diffs []drift.FieldDiff) []string {
	paths := make([]string, 0, len(diffs))
	for _, d := range diffs {
		paths = append(paths, d.FieldPath)
	}
	slices.Sort(paths)
	return paths
}

// evaluateRules resolves which rules apply to this agent/domain (matching
// policy assignments by scope, docs/compliance/07-POLICY-ENGINE.md) and
// records one verdict per rule — with structured evidence, platform
// applicability, and active-exception tagging (docs/compliance §2, §17, §21).
func (in *Ingester) evaluateRules(ctx context.Context, snap Snapshot) (int, error) {
	attrs, err := in.store.LoadAgentAttributes(ctx, snap.AgentID)
	if err != nil {
		return 0, fmt.Errorf("loading agent attributes for evaluation: %w", err)
	}

	matchedSetIDs, err := in.matchedPolicySetIDs(ctx, attrs)
	if err != nil {
		return 0, err
	}
	if len(matchedSetIDs) == 0 {
		return 0, nil // no policy set assigned to this agent's scope — nothing to evaluate
	}

	activeRules, err := in.store.RulesForPolicySetsAndDomain(ctx, matchedSetIDs, snap.Domain)
	if err != nil {
		return 0, err
	}
	return in.evaluateAndRecord(ctx, snap.AgentID, attrs, activeRules, snap.Facts)
}

// matchedPolicySetIDs loads active policy_assignments and filters them
// against attrs — split out so both the per-domain snapshot path
// (evaluateRules) and the resource-triggered incremental path
// (reevaluateAffectedRules) resolve scope the same way.
func (in *Ingester) matchedPolicySetIDs(ctx context.Context, attrs storage.AgentAttributes) ([]uuid.UUID, error) {
	assignments, err := in.store.LoadActivePolicyAssignments(ctx)
	if err != nil {
		return nil, err
	}
	return policy.MatchingSetIDs(attrs, assignments), nil
}

// evaluateAndRecord evaluates activeRules against facts and inserts one
// rule_evaluations row per rule — the shared core between a fresh domain
// snapshot's full evaluation and a resource-change-triggered partial
// re-evaluation (docs/compliance §39, §40). Returns the number of rules
// evaluated.
func (in *Ingester) evaluateAndRecord(
	ctx context.Context,
	agentID uuid.UUID,
	attrs storage.AgentAttributes,
	activeRules []storage.RuleWithPolicySet,
	facts map[string]any,
) (int, error) {
	if len(activeRules) == 0 {
		return 0, nil
	}
	platform := scope.PlatformID(attrs.OsDistro, attrs.OsVersion)

	ruleIDs := make([]uuid.UUID, 0, len(activeRules))
	for _, r := range activeRules {
		id, err := uuid.Parse(r.Rule.ID)
		if err != nil {
			return 0, fmt.Errorf("rule %s has a non-UUID ID %q: %w", r.RuleKey, r.Rule.ID, err)
		}
		ruleIDs = append(ruleIDs, id)
	}
	exceptions, err := in.store.LoadActiveExceptionsForRules(ctx, ruleIDs)
	if err != nil {
		return 0, err
	}

	for i, r := range activeRules {
		verdict := in.evaluator.Evaluate(ctx, r.Rule, facts, platform)

		var actualValueJSON, evidenceJSON, expectedValueJSON []byte
		if verdict.ActualValue != nil {
			actualValueJSON, _ = json.Marshal(verdict.ActualValue)
		}
		if verdict.Evidence != nil {
			evidenceJSON, _ = json.Marshal(verdict.Evidence)
		}
		if r.Rule.ExpectedValue != nil {
			expectedValueJSON, _ = json.Marshal(r.Rule.ExpectedValue)
		}
		errMsg := ""
		if verdict.Err != nil {
			errMsg = verdict.Err.Error()
		}

		var exceptionID *uuid.UUID
		if verdict.Result == rules.ResultFail {
			if id, ok := matchException(exceptions, ruleIDs[i], agentID, attrs); ok {
				exceptionID = &id
			}
		}

		if err := in.store.InsertRuleEvaluation(
			ctx, agentID, ruleIDs[i], r.PolicySetID,
			string(verdict.Result), actualValueJSON, evidenceJSON, expectedValueJSON,
			errMsg, verdict.EvidenceHash, "lokilinux-agent", exceptionID,
		); err != nil {
			return len(activeRules), err
		}
	}

	return len(activeRules), nil
}

// reevaluateAffectedRules is the incremental-evaluation path
// (docs/compliance §12, §39, §40): given the file paths that just changed
// on this agent, look up exactly which rules depend on them
// (compliance_rule_resources, resource_type='FILE') and re-evaluate only
// those rules — never the whole domain's rule set, and never every domain.
// A rule's domain (e.g. sshd) generally differs from the file_integrity
// snapshot's domain, so each affected rule is re-evaluated against that
// domain's own latest stored snapshot facts, not the FIM snapshot's facts.
func (in *Ingester) reevaluateAffectedRules(ctx context.Context, agentID uuid.UUID, paths []string) error {
	if len(paths) == 0 {
		return nil
	}
	affected, err := in.store.RulesForResourcePaths(ctx, "FILE", paths)
	if err != nil {
		return err
	}
	if len(affected) == 0 {
		return nil
	}

	byDomain := make(map[string][]uuid.UUID)
	for _, a := range affected {
		byDomain[a.Domain] = append(byDomain[a.Domain], a.RuleID)
	}

	attrs, err := in.store.LoadAgentAttributes(ctx, agentID)
	if err != nil {
		return fmt.Errorf("loading agent attributes for incremental evaluation: %w", err)
	}
	matchedSetIDs, err := in.matchedPolicySetIDs(ctx, attrs)
	if err != nil {
		return err
	}
	if len(matchedSetIDs) == 0 {
		return nil
	}

	for domain, wantedIDs := range byDomain {
		latestHash, found, err := in.store.LatestSnapshotHash(ctx, agentID, domain)
		if err != nil {
			return err
		}
		if !found {
			continue // no snapshot collected yet for this domain — nothing to re-evaluate against
		}
		body, err := in.store.GetBlobBody(ctx, latestHash)
		if err != nil {
			return err
		}
		var facts map[string]any
		if err := json.Unmarshal(body, &facts); err != nil {
			return fmt.Errorf("decoding latest %s snapshot for incremental evaluation: %w", domain, err)
		}

		domainRules, err := in.store.RulesForPolicySetsAndDomain(ctx, matchedSetIDs, domain)
		if err != nil {
			return err
		}
		subset := filterRulesByID(domainRules, wantedIDs)
		if _, err := in.evaluateAndRecord(ctx, agentID, attrs, subset, facts); err != nil {
			return err
		}
	}
	return nil
}

// filterRulesByID keeps only the rules whose ID is in wanted — activeRules
// (from RulesForPolicySetsAndDomain) already carries every rule for the
// domain; this narrows it to exactly the resource-affected subset without a
// second, more complex query.
func filterRulesByID(activeRules []storage.RuleWithPolicySet, wanted []uuid.UUID) []storage.RuleWithPolicySet {
	wantSet := make(map[string]struct{}, len(wanted))
	for _, id := range wanted {
		wantSet[id.String()] = struct{}{}
	}
	var out []storage.RuleWithPolicySet
	for _, r := range activeRules {
		if _, ok := wantSet[r.Rule.ID]; ok {
			out = append(out, r)
		}
	}
	return out
}

// matchException finds the first active exception covering (ruleID, agentID)
// — either scoped directly to this agent, or (agent_id NULL) to a broader
// selector this agent's attributes match. The real FAIL result stays stored
// by the caller; this only tags which exception waived it
// (docs/compliance §17: never silently overwrite).
func matchException(exceptions []storage.ActiveException, ruleID, agentID uuid.UUID, attrs storage.AgentAttributes) (uuid.UUID, bool) {
	sAttrs := scope.AgentAttributes{
		OsDistro: attrs.OsDistro, OsVersion: attrs.OsVersion,
		Category: attrs.Category, Project: attrs.Project,
	}
	for _, ex := range exceptions {
		if ex.RuleID != ruleID {
			continue
		}
		if ex.AgentID != nil {
			if *ex.AgentID == agentID {
				return ex.ID, true
			}
			continue
		}
		if scope.Matches(ex.ScopeSelector, sAttrs) {
			return ex.ID, true
		}
	}
	return uuid.Nil, false
}

// categoryScore is one category's computed score sample, ready for
// storage.InsertComplianceScore.
type categoryScore struct {
	category                      string
	score                         float64
	passed, failed, notApplicable int
}

// computeCategoryScores is the pure half of updateComplianceScores — given
// an agent's latest evaluation set, returns one categoryScore per category
// present plus a synthetic "overall" entry (the unweighted mean of the
// categories that had at least one scoreable PASS/FAIL rule, matching the
// brief's dashboard example in docs/compliance/07-POLICY-ENGINE.md §4).
// Split out from the DB-writing method so this is testable without a real
// Postgres.
func computeCategoryScores(evaluations []storage.EvaluationSummary) []categoryScore {
	type bucket struct{ passed, failed, notApplicable int }
	buckets := map[string]*bucket{}
	var order []string
	for _, e := range evaluations {
		category := scoring.Classify(e.Domain)
		b, ok := buckets[category]
		if !ok {
			b = &bucket{}
			buckets[category] = b
			order = append(order, category)
		}
		switch rules.Result(e.Result) {
		case rules.ResultPass:
			b.passed++
		case rules.ResultFail:
			b.failed++
		case rules.ResultNotApplicable:
			b.notApplicable++
		}
	}

	var out []categoryScore
	var scoredSum float64
	var scoredCount int
	for _, category := range order {
		b := buckets[category]
		total := b.passed + b.failed
		var score float64
		if total > 0 {
			score = 100.0 * float64(b.passed) / float64(total)
			scoredSum += score
			scoredCount++
		}
		out = append(out, categoryScore{category: category, score: score, passed: b.passed, failed: b.failed, notApplicable: b.notApplicable})
	}

	if scoredCount > 0 {
		out = append(out, categoryScore{category: "overall", score: scoredSum / float64(scoredCount)})
	}

	return out
}

// updateComplianceScores recomputes every category score for one agent from
// its full current rule_evaluations set (all domains, not just the one that
// just changed) and appends one compliance_scores row per category —
// migration 016 declared this table but nothing wrote to it until this.
func (in *Ingester) updateComplianceScores(ctx context.Context, agentID uuid.UUID) error {
	evaluations, err := in.store.LatestEvaluationsForAgent(ctx, agentID)
	if err != nil {
		return fmt.Errorf("loading latest evaluations for scoring: %w", err)
	}

	for _, cs := range computeCategoryScores(evaluations) {
		if err := in.store.InsertComplianceScore(ctx, agentID, cs.category, cs.score, cs.passed, cs.failed, cs.notApplicable); err != nil {
			return err
		}
	}
	return nil
}
