// Package storage is the pgx-backed persistence layer for lokilinux-compliance.
//
// ponytail: hand-written queries, not sqlc-generated ones. docs/compliance/02-GO-SERVICE.md
// mentions sqlc as the eventual choice for schema-verified queries at build
// time, but that needs a working toolchain + generator step wired into the
// build; plain pgx queries against the schema in migration 015/016 are
// enough for this first vertical slice. Swap to sqlc if/when query surface
// area grows enough that hand-written SQL becomes the error-prone part.
package storage

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/lokilinux/compliance/internal/rules"
	"github.com/lokilinux/compliance/internal/scope"
)

// dbtx is the query surface shared by *pgxpool.Pool and pgx.Tx — Store
// methods run against either, which is what makes Transact possible without
// duplicating every statement.
type dbtx interface {
	Exec(ctx context.Context, sql string, arguments ...any) (pgconn.CommandTag, error)
	QueryRow(ctx context.Context, sql string, arguments ...any) pgx.Row
	Query(ctx context.Context, sql string, arguments ...any) (pgx.Rows, error)
}

type Store struct {
	pool *pgxpool.Pool
	db   dbtx // pool outside a transaction, the tx handle inside Transact
}

// Open connects using databaseURL and verifies connectivity with a ping —
// a misconfigured DATABASE_URL should fail at startup, not on the first
// real query. maxConns caps pool size (<=0 means pgx's default).
func Open(ctx context.Context, databaseURL string, maxConns int32) (*Store, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parsing database URL: %w", err)
	}
	if maxConns > 0 {
		cfg.MaxConns = maxConns
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("creating pgx pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("pinging database: %w", err)
	}
	return &Store{pool: pool, db: pool}, nil
}

func (s *Store) Close() { s.pool.Close() }

// Transact runs fn against a single Postgres transaction — every Store call
// inside fn writes atomically: any error rolls back the whole attempt, so a
// crash or shutdown mid-ingest can no longer strand partial state that a
// JetStream redelivery would then compound.
func (s *Store) Transact(ctx context.Context, fn func(tx *Store) error) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("beginning transaction: %w", err)
	}
	txs := &Store{pool: s.pool, db: tx}
	if err := fn(txs); err != nil {
		if rbErr := tx.Rollback(ctx); rbErr != nil {
			return errors.Join(err, fmt.Errorf("rolling back transaction: %w", rbErr))
		}
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("committing transaction: %w", err)
	}
	return nil
}

// UpsertInventoryBlob stores the canonical body once per content_hash
// (docs/compliance/01-DATA-MODEL.md §3, D3) — a second write of the same
// hash increments ref_count instead of duplicating storage.
func (s *Store) UpsertInventoryBlob(ctx context.Context, contentHash string, body []byte, algo string) error {
	_, err := s.db.Exec(ctx, `
		INSERT INTO inventory_blobs (content_hash, body, algo, size_bytes, ref_count)
		VALUES ($1, $2, $3, $4, 1)
		ON CONFLICT (content_hash) DO UPDATE
		SET ref_count = inventory_blobs.ref_count + 1
	`, contentHash, body, algo, len(body))
	if err != nil {
		return fmt.Errorf("upserting inventory blob %s: %w", contentHash, err)
	}
	return nil
}

// InsertInventorySnapshot records a new immutable snapshot pointer. Never
// UPDATE an existing row — "current" is defined as the latest row per
// (agent_id, domain), per docs/compliance/01-DATA-MODEL.md §3.
func (s *Store) InsertInventorySnapshot(ctx context.Context, agentID uuid.UUID, domain, contentHash string) (uuid.UUID, error) {
	var id uuid.UUID
	err := s.db.QueryRow(ctx, `
		INSERT INTO inventory_snapshots (agent_id, domain, content_hash)
		VALUES ($1, $2, $3)
		RETURNING id
	`, agentID, domain, contentHash).Scan(&id)
	if err != nil {
		return uuid.Nil, fmt.Errorf("inserting inventory snapshot (%s/%s): %w", agentID, domain, err)
	}
	return id, nil
}

// LatestSnapshotHash returns the content_hash of the most recent snapshot
// for (agentID, domain), and false if none exists yet — the comparison
// point for delta-sync's resync_domains decision (docs/compliance/04-PROTOCOL.md §3).
func (s *Store) LatestSnapshotHash(ctx context.Context, agentID uuid.UUID, domain string) (contentHash string, found bool, err error) {
	err = s.db.QueryRow(ctx, `
		SELECT content_hash FROM inventory_snapshots
		WHERE agent_id = $1 AND domain = $2
		ORDER BY taken_at DESC LIMIT 1
	`, agentID, domain).Scan(&contentHash)
	if err != nil {
		if err == pgx.ErrNoRows {
			return "", false, nil
		}
		return "", false, fmt.Errorf("querying latest snapshot hash (%s/%s): %w", agentID, domain, err)
	}
	return contentHash, true, nil
}

// GetBlobBody returns the raw canonical JSON body for a content_hash — used
// to decode the previous snapshot's facts for drift comparison.
func (s *Store) GetBlobBody(ctx context.Context, contentHash string) ([]byte, error) {
	var body []byte
	err := s.db.QueryRow(ctx, `SELECT body FROM inventory_blobs WHERE content_hash = $1`, contentHash).Scan(&body)
	if err != nil {
		return nil, fmt.Errorf("fetching blob body %s: %w", contentHash, err)
	}
	return body, nil
}

// InsertDriftEvent records one drift.Event as a drift_events row plus one
// drift_details row per field diff — both hypertables (migration 017).
// Always the start of a fresh incident (status OPEN, occurrences 1) — the
// caller (ingest.recordOrCorrelateDrift) only reaches this after
// IncrementDriftOccurrence found no existing OPEN/ACKNOWLEDGED match for
// correlationKey (docs/compliance §9).
func (s *Store) InsertDriftEvent(
	ctx context.Context,
	agentID uuid.UUID,
	domain, comparedAgainst, severity, changeType, summary, correlationKey string,
	fieldDiffs []DriftFieldDiff,
) (uuid.UUID, error) {
	now := time.Now().UTC()
	var eventID uuid.UUID
	err := s.db.QueryRow(ctx, `
		INSERT INTO drift_events (
			time, agent_id, domain, compared_against, severity, change_type, summary,
			correlation_key, status, occurrences, first_seen, last_seen
		)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'OPEN', 1, $1, $1)
		RETURNING id
	`, now, agentID, domain, comparedAgainst, severity, changeType, summary, correlationKey).Scan(&eventID)
	if err != nil {
		return uuid.Nil, fmt.Errorf("inserting drift event (agent=%s domain=%s): %w", agentID, domain, err)
	}

	for _, d := range fieldDiffs {
		_, err := s.db.Exec(ctx, `
			INSERT INTO drift_details (time, drift_event_time, drift_event_id, field_path, old_value, new_value)
			VALUES ($1, $2, $3, $4, $5, $6)
		`, now, now, eventID, d.FieldPath, d.OldValue, d.NewValue)
		if err != nil {
			return eventID, fmt.Errorf("inserting drift detail %s for event %s: %w", d.FieldPath, eventID, err)
		}
	}
	return eventID, nil
}

// IncrementDriftOccurrence bumps occurrences/last_seen on an existing
// OPEN or ACKNOWLEDGED drift_events row matching (agentID, correlationKey)
// instead of inserting a duplicate — the dedup half of docs/compliance §9's
// "100 occurrences, one incident." Returns found=false when no such row
// exists (caller then inserts a fresh incident) — a RESOLVED/SUPPRESSED/
// EXCEPTION row with the same key correctly does not match, so a
// deviation that reappears after being fixed opens a new incident rather
// than silently reopening a closed one.
func (s *Store) IncrementDriftOccurrence(ctx context.Context, agentID uuid.UUID, correlationKey string) (bool, error) {
	tag, err := s.db.Exec(ctx, `
		UPDATE drift_events SET occurrences = occurrences + 1, last_seen = now()
		WHERE agent_id = $1 AND correlation_key = $2 AND status IN ('OPEN', 'ACKNOWLEDGED')
	`, agentID, correlationKey)
	if err != nil {
		return false, fmt.Errorf("incrementing drift occurrence (agent=%s): %w", agentID, err)
	}
	return tag.RowsAffected() > 0, nil
}

// DriftFieldDiff mirrors drift.FieldDiff but with pre-marshaled JSON values
// (storage doesn't import the drift package's Go-typed OldValue/NewValue —
// the caller marshals, keeping this package free of a rules/drift import
// cycle risk as those packages grow).
type DriftFieldDiff struct {
	FieldPath string
	OldValue  []byte
	NewValue  []byte
}

// PolicyAssignment is one enabled policy_assignments row — the input set
// policy.MatchingSetIDs filters by the agent's attributes
// (docs/compliance/07-POLICY-ENGINE.md).
type PolicyAssignment struct {
	PolicySetID   uuid.UUID
	ScopeType     string
	ScopeSelector map[string]any
}

// LoadActivePolicyAssignments returns every enabled policy_assignments row,
// every scope_type — not just GLOBAL. Full scope-tree resolution happens in
// internal/policy (mirrors internal/baseline's resolver), replacing the
// earlier GLOBAL-only restriction.
func (s *Store) LoadActivePolicyAssignments(ctx context.Context) ([]PolicyAssignment, error) {
	rowsResult, err := s.db.Query(ctx, `
		SELECT policy_set_id, scope_type, scope_selector
		FROM policy_assignments
		WHERE is_enabled = true
	`)
	if err != nil {
		return nil, fmt.Errorf("querying active policy assignments: %w", err)
	}
	defer rowsResult.Close()

	var out []PolicyAssignment
	for rowsResult.Next() {
		var a PolicyAssignment
		if err := rowsResult.Scan(&a.PolicySetID, &a.ScopeType, &a.ScopeSelector); err != nil {
			return nil, fmt.Errorf("scanning policy assignment row: %w", err)
		}
		out = append(out, a)
	}
	return out, rowsResult.Err()
}

// RulesForPolicySetsAndDomain returns ACTIVE (Enterprise Compliance plan
// U3/KTD2 — REFERENCE_ONLY/DISABLED never reach the evaluator) CEL/
// OVAL_UNMAPPED/OSCAP_FALLBACK rules for a domain that belong to any of
// policySetIDs — the caller (ingest.go)
// resolves policySetIDs via policy.MatchingSetIDs first, keeping scope
// resolution and rule loading as separate, independently testable steps.
// An empty policySetIDs returns no rows (no matching assignment for this
// agent), not "every rule".
func (s *Store) RulesForPolicySetsAndDomain(ctx context.Context, policySetIDs []uuid.UUID, domain string) ([]RuleWithPolicySet, error) {
	if len(policySetIDs) == 0 {
		return nil, nil
	}
	rowsResult, err := s.db.Query(ctx, `
		SELECT DISTINCT cr.id, cr.rule_key, cr.check_source, cr.check_expr,
		       cr.platform_filter, cr.expected_value, psr.policy_set_id
		FROM compliance_rules cr
		JOIN policy_set_rules psr ON psr.rule_id = cr.id
		WHERE cr.domain = $1 AND cr.status = 'ACTIVE' AND psr.policy_set_id = ANY($2)
	`, domain, policySetIDs)
	if err != nil {
		return nil, fmt.Errorf("querying rules for domain %s: %w", domain, err)
	}
	defer rowsResult.Close()

	var out []RuleWithPolicySet
	var ruleIDs []uuid.UUID
	for rowsResult.Next() {
		var r RuleWithPolicySet
		var checkSource string
		var expectedValueJSON []byte
		if err := rowsResult.Scan(
			&r.Rule.ID, &r.RuleKey, &checkSource, &r.Rule.CheckExpr,
			&r.Rule.PlatformFilter, &expectedValueJSON, &r.PolicySetID,
		); err != nil {
			return nil, fmt.Errorf("scanning active rule row: %w", err)
		}
		r.Rule.CheckSource = rules.CheckSource(checkSource)
		if len(expectedValueJSON) > 0 {
			if err := json.Unmarshal(expectedValueJSON, &r.Rule.ExpectedValue); err != nil {
				return nil, fmt.Errorf("decoding expected_value for rule %s: %w", r.RuleKey, err)
			}
		}
		id, err := uuid.Parse(r.Rule.ID)
		if err != nil {
			return nil, fmt.Errorf("rule %s has a non-UUID id: %w", r.RuleKey, err)
		}
		ruleIDs = append(ruleIDs, id)
		out = append(out, r)
	}
	if err := rowsResult.Err(); err != nil {
		return nil, err
	}

	evidencePaths, err := s.evidencePathsForRules(ctx, ruleIDs)
	if err != nil {
		return nil, err
	}
	for i := range out {
		out[i].Rule.EvidencePaths = evidencePaths[out[i].Rule.ID]
	}
	return out, nil
}

// evidencePathsForRules bulk-loads FACT_PATH resources for a set of rules in
// one query — never N+1 per rule (docs/compliance §38, fleet-scale
// requirement), keyed by rule ID string to match rules.Rule.ID's type.
func (s *Store) evidencePathsForRules(ctx context.Context, ruleIDs []uuid.UUID) (map[string][]string, error) {
	out := map[string][]string{}
	if len(ruleIDs) == 0 {
		return out, nil
	}
	rowsResult, err := s.db.Query(ctx, `
		SELECT rule_id, resource_path FROM compliance_rule_resources
		WHERE resource_type = 'FACT_PATH' AND rule_id = ANY($1)
	`, ruleIDs)
	if err != nil {
		return nil, fmt.Errorf("querying evidence paths: %w", err)
	}
	defer rowsResult.Close()

	for rowsResult.Next() {
		var ruleID uuid.UUID
		var path string
		if err := rowsResult.Scan(&ruleID, &path); err != nil {
			return nil, fmt.Errorf("scanning evidence path row: %w", err)
		}
		key := ruleID.String()
		out[key] = append(out[key], path)
	}
	return out, rowsResult.Err()
}

// RuleWithPolicySet pairs a rules.Rule with the extra columns storage needs
// but the evaluator doesn't: which policy set it was matched through (part
// of rule_evaluations' composite key) and its human-readable key (logging).
type RuleWithPolicySet struct {
	Rule        rules.Rule
	RuleKey     string
	PolicySetID uuid.UUID
	// Domain is only populated by RulesForPolicySet (which spans every
	// domain in one policy set); RulesForPolicySetsAndDomain's caller
	// already knows the domain it queried for, so it leaves this zero.
	Domain string
}

// ActiveException is one live compliance_exceptions row — expires_at > now()
// and status = 'ACTIVE' already applied by the query, so callers never need
// to re-check expiry (docs/compliance §17).
type ActiveException struct {
	ID            uuid.UUID
	RuleID        uuid.UUID
	AgentID       *uuid.UUID
	ScopeSelector map[string]any
}

// LoadActiveExceptionsForRules bulk-loads active exceptions for a set of
// rules (one query per domain evaluation batch, not per rule — same
// fleet-scale reasoning as evidencePathsForRules).
func (s *Store) LoadActiveExceptionsForRules(ctx context.Context, ruleIDs []uuid.UUID) ([]ActiveException, error) {
	if len(ruleIDs) == 0 {
		return nil, nil
	}
	rowsResult, err := s.db.Query(ctx, `
		SELECT id, rule_id, agent_id, scope_selector
		FROM compliance_exceptions
		WHERE status = 'ACTIVE' AND expires_at > now() AND rule_id = ANY($1)
	`, ruleIDs)
	if err != nil {
		return nil, fmt.Errorf("querying active exceptions: %w", err)
	}
	defer rowsResult.Close()

	var out []ActiveException
	for rowsResult.Next() {
		var e ActiveException
		if err := rowsResult.Scan(&e.ID, &e.RuleID, &e.AgentID, &e.ScopeSelector); err != nil {
			return nil, fmt.Errorf("scanning active exception row: %w", err)
		}
		out = append(out, e)
	}
	return out, rowsResult.Err()
}

// InsertRuleEvaluation records one verdict. rule_evaluations is a hypertable
// (migration 016) — every call is a plain INSERT, never an UPDATE.
// exceptionID is nil when no active exception covered this verdict — the
// real evaluated result is always what's stored, exception_id only tags it
// (docs/compliance §17: never silently overwrite FAIL with a fake PASS).
func (s *Store) InsertRuleEvaluation(
	ctx context.Context,
	agentID, ruleID, policySetID uuid.UUID,
	result string,
	actualValue, evidence, expectedValue []byte,
	errMsg, evidenceHash, source string,
	exceptionID *uuid.UUID,
) error {
	_, err := s.db.Exec(ctx, `
		INSERT INTO rule_evaluations (
			time, agent_id, rule_id, policy_set_id, result, actual_value, evidence,
			error_message, expected_value, evidence_hash, source, exception_id
		)
		VALUES ($1, $2, $3, $4, $5, $6, $7, NULLIF($8, ''), $9, NULLIF($10, ''), NULLIF($11, ''), $12)
	`, time.Now().UTC(), agentID, ruleID, policySetID, result, actualValue, evidence,
		errMsg, expectedValue, evidenceHash, source, exceptionID)
	if err != nil {
		return fmt.Errorf("inserting rule evaluation (agent=%s rule=%s): %w", agentID, ruleID, err)
	}
	return nil
}

// ExistingFileHashes returns every currently-tracked file_hashes row for an
// agent, keyed by path — the comparison set diffFileIntegrity needs
// (docs/compliance/08-DRIFT-FIM.md §per-file drift, migration 017).
// ExistingFileHash is one file_hashes row's current-state metadata — the
// comparison set diffFileIntegrity needs to detect not just content
// changes but PERMISSION_CHANGED/OWNER_CHANGED (migration 025's
// old_mode/old_uid/old_gid columns, F11). Mode/UID/GID are pointers since
// an agent predating F11 (or a row written before this) may have NULL
// there — nil means "unknown," never compared as if it were 0.
type ExistingFileHash struct {
	Hash string
	Mode *int32
	UID  *int32
	GID  *int32
}

func (s *Store) ExistingFileHashes(ctx context.Context, agentID uuid.UUID) (map[string]ExistingFileHash, error) {
	rowsResult, err := s.db.Query(ctx, `SELECT path, hash, mode, uid, gid FROM file_hashes WHERE agent_id = $1`, agentID)
	if err != nil {
		return nil, fmt.Errorf("querying existing file hashes for agent %s: %w", agentID, err)
	}
	defer rowsResult.Close()

	out := map[string]ExistingFileHash{}
	for rowsResult.Next() {
		var path string
		var e ExistingFileHash
		if err := rowsResult.Scan(&path, &e.Hash, &e.Mode, &e.UID, &e.GID); err != nil {
			return nil, fmt.Errorf("scanning file hash row: %w", err)
		}
		out[path] = e
	}
	return out, rowsResult.Err()
}

// UpsertFileHash records the current hash+metadata for one watched file —
// file_hashes is current-state-only (migration 017), overwritten in place,
// unlike file_changes which is an append-only history.
func (s *Store) UpsertFileHash(ctx context.Context, agentID uuid.UUID, path, algo, hash string, sizeBytes int64, mode, uid, gid int32) error {
	_, err := s.db.Exec(ctx, `
		INSERT INTO file_hashes (agent_id, path, algo, hash, size_bytes, mode, uid, gid, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
		ON CONFLICT (agent_id, path) DO UPDATE
		SET algo = EXCLUDED.algo, hash = EXCLUDED.hash, size_bytes = EXCLUDED.size_bytes,
		    mode = EXCLUDED.mode, uid = EXCLUDED.uid, gid = EXCLUDED.gid, updated_at = now()
	`, agentID, path, algo, hash, sizeBytes, mode, uid, gid)
	if err != nil {
		return fmt.Errorf("upserting file hash (agent=%s path=%s): %w", agentID, path, err)
	}
	return nil
}

// DeleteFileHash removes a file_hashes row once its DELETED file_changes
// event has been recorded — file_hashes only ever tracks files that
// currently exist on the agent.
func (s *Store) DeleteFileHash(ctx context.Context, agentID uuid.UUID, path string) error {
	_, err := s.db.Exec(ctx, `DELETE FROM file_hashes WHERE agent_id = $1 AND path = $2`, agentID, path)
	if err != nil {
		return fmt.Errorf("deleting file hash (agent=%s path=%s): %w", agentID, path, err)
	}
	return nil
}

// FileChangeMetadata carries the optional old/new mode/uid/gid for one
// file_changes row (migration 025) — nil fields insert as SQL NULL, pgx
// handles a nil *int32 natively.
type FileChangeMetadata struct {
	OldMode, NewMode *int32
	OldUID, NewUID   *int32
	OldGID, NewGID   *int32
}

// InsertFileChange records one file_changes event — a hypertable (migration
// 017), append-only, one row per detected change. Empty oldHash/newHash
// (CREATED has no old, DELETED has no new) are stored as SQL NULL.
func (s *Store) InsertFileChange(ctx context.Context, agentID uuid.UUID, path, oldHash, newHash, changeKind string, meta FileChangeMetadata) error {
	_, err := s.db.Exec(ctx, `
		INSERT INTO file_changes (
			time, agent_id, path, old_hash, new_hash, change_kind,
			old_mode, new_mode, old_uid, new_uid, old_gid, new_gid
		)
		VALUES ($1, $2, $3, NULLIF($4, ''), NULLIF($5, ''), $6, $7, $8, $9, $10, $11, $12)
	`, time.Now().UTC(), agentID, path, oldHash, newHash, changeKind,
		meta.OldMode, meta.NewMode, meta.OldUID, meta.NewUID, meta.OldGID, meta.NewGID)
	if err != nil {
		return fmt.Errorf("inserting file change (agent=%s path=%s): %w", agentID, path, err)
	}
	return nil
}

// ExpirePendingExceptions flips ACTIVE compliance_exceptions past their
// expires_at to EXPIRED (docs/compliance §17: "After expiration ->
// EXCEPTION EXPIRED -> RULE FAIL") — the evaluation path never treats a
// waiver as active once this runs, since evaluateAndRecord's exception
// lookup already filters on status = 'ACTIVE'.
func (s *Store) ExpirePendingExceptions(ctx context.Context) (int64, error) {
	tag, err := s.db.Exec(ctx, `
		UPDATE compliance_exceptions SET status = 'EXPIRED', updated_at = now()
		WHERE status = 'ACTIVE' AND expires_at <= now()
	`)
	if err != nil {
		return 0, fmt.Errorf("expiring compliance exceptions: %w", err)
	}
	return tag.RowsAffected(), nil
}

// LoadFileIntegrityIgnorePatterns returns every GLOBAL-scope
// file_integrity_ignores.path_pattern (migration 017, unused before this).
//
// ponytail: GLOBAL-scope only — the table supports per-scope ignore rules
// (scope_type/scope_selector), but resolving those against an agent needs
// the same scope.Matches call sites already do elsewhere; not worth the
// extra query on every file_integrity snapshot until a real per-scope
// ignore rule is needed. Upgrade path: extend the WHERE clause once that's
// requested, same honest-v1 pattern as ActiveRulesForDomain's predecessor.
func (s *Store) LoadFileIntegrityIgnorePatterns(ctx context.Context) ([]string, error) {
	rowsResult, err := s.db.Query(ctx, `SELECT path_pattern FROM file_integrity_ignores WHERE scope_type = 'GLOBAL'`)
	if err != nil {
		return nil, fmt.Errorf("querying file integrity ignore patterns: %w", err)
	}
	defer rowsResult.Close()

	var out []string
	for rowsResult.Next() {
		var p string
		if err := rowsResult.Scan(&p); err != nil {
			return nil, fmt.Errorf("scanning ignore pattern row: %w", err)
		}
		out = append(out, p)
	}
	return out, rowsResult.Err()
}

// AffectedRule pairs a rule with its domain — resolving which rules a
// changed resource path affects necessarily crosses domains (a changed
// /etc/ssh/sshd_config can affect sshd-domain rules while the snapshot that
// detected the change is itself the file_integrity domain).
type AffectedRule struct {
	RuleID uuid.UUID
	Domain string
}

// RulesForResourcePaths resolves compliance_rule_resources -> compliance_rules
// for a set of changed paths in one query (docs/compliance §40) — the
// dependency-index lookup incremental evaluation needs, never a per-path
// query in a loop.
func (s *Store) RulesForResourcePaths(ctx context.Context, resourceType string, paths []string) ([]AffectedRule, error) {
	if len(paths) == 0 {
		return nil, nil
	}
	rowsResult, err := s.db.Query(ctx, `
		SELECT DISTINCT crr.rule_id, cr.domain
		FROM compliance_rule_resources crr
		JOIN compliance_rules cr ON cr.id = crr.rule_id
		WHERE crr.resource_type = $1 AND crr.resource_path = ANY($2) AND cr.status = 'ACTIVE'
	`, resourceType, paths)
	if err != nil {
		return nil, fmt.Errorf("querying rules for resource paths: %w", err)
	}
	defer rowsResult.Close()

	var out []AffectedRule
	for rowsResult.Next() {
		var a AffectedRule
		if err := rowsResult.Scan(&a.RuleID, &a.Domain); err != nil {
			return nil, fmt.Errorf("scanning affected rule row: %w", err)
		}
		out = append(out, a)
	}
	return out, rowsResult.Err()
}

// EvaluationSummary is one agent's latest verdict for one rule, joined with
// the rule's domain — the input to per-category score computation.
type EvaluationSummary struct {
	Domain   string
	Result   string
	Severity string // compliance_rules.severity — LOW/MEDIUM/HIGH/CRITICAL (plan U5/KTD4 weighting)
}

// LatestEvaluationsForAgent returns the most recent verdict per rule for
// one agent (DISTINCT ON rule_id), across every domain — compliance_scores
// (migration 016) had no writer before this; this is the full input set a
// rescore needs after any domain's rule_evaluations change.
func (s *Store) LatestEvaluationsForAgent(ctx context.Context, agentID uuid.UUID) ([]EvaluationSummary, error) {
	rowsResult, err := s.db.Query(ctx, `
		SELECT DISTINCT ON (re.rule_id) cr.domain, re.result, cr.severity
		FROM rule_evaluations re
		JOIN compliance_rules cr ON cr.id = re.rule_id
		WHERE re.agent_id = $1
		ORDER BY re.rule_id, re.time DESC
	`, agentID)
	if err != nil {
		return nil, fmt.Errorf("querying latest evaluations for agent %s: %w", agentID, err)
	}
	defer rowsResult.Close()

	var out []EvaluationSummary
	for rowsResult.Next() {
		var e EvaluationSummary
		if err := rowsResult.Scan(&e.Domain, &e.Result, &e.Severity); err != nil {
			return nil, fmt.Errorf("scanning evaluation summary row: %w", err)
		}
		out = append(out, e)
	}
	return out, rowsResult.Err()
}

// InsertComplianceScore records one category's score sample for an agent —
// an append-only hypertable row (migration 016), the raw input
// compliance_scores_daily aggregates for the fleet trend chart.
//
// weightedScore/severityBreakdown/unknownCount are the plan U5/KTD4
// projection (migration 037, nullable alongside the legacy score/*_count
// columns above which keep their exact pre-existing meaning). breakdown may
// be nil (never scored / no severity data) — stored as SQL NULL, not "{}",
// so a consumer can tell "not computed" apart from "computed, all zero".
func (s *Store) InsertComplianceScore(
	ctx context.Context,
	agentID uuid.UUID,
	category string,
	score float64,
	passedCount, failedCount, notApplicableCount int,
	weightedScore float64,
	severityBreakdown map[string]map[string]int,
	unknownCount int,
) error {
	var breakdownJSON []byte
	if len(severityBreakdown) > 0 {
		var err error
		breakdownJSON, err = json.Marshal(severityBreakdown)
		if err != nil {
			return fmt.Errorf("marshaling severity breakdown (agent=%s category=%s): %w", agentID, category, err)
		}
	}
	_, err := s.db.Exec(ctx, `
		INSERT INTO compliance_scores (
			time, agent_id, category, score, passed_count, failed_count, not_applicable_count,
			weighted_score, severity_breakdown, unknown_count
		)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
	`, time.Now().UTC(), agentID, category, score, passedCount, failedCount, notApplicableCount,
		weightedScore, breakdownJSON, unknownCount)
	if err != nil {
		return fmt.Errorf("inserting compliance score (agent=%s category=%s): %w", agentID, category, err)
	}
	return nil
}

// DispatchScheduledJobs transitions every 'SCHEDULED' job whose
// scheduled_time has arrived to 'QUEUED', making it visible to
// AgentService.get_pending_jobs on the target agents' next heartbeat —
// jobs.scheduled_time is stored by the existing Python job-creation path
// (backend/lokilinux/services/job_service.py) but had no dispatcher reading
// it anywhere in the codebase before this (docs/compliance/02-GO-SERVICE.md §4).
// Only the leader replica should call this (docs/compliance/13-OPS.md).
func (s *Store) DispatchScheduledJobs(ctx context.Context) (int64, error) {
	tag, err := s.db.Exec(ctx, `
		UPDATE jobs SET status = 'QUEUED', updated_at = now()
		WHERE status = 'SCHEDULED' AND scheduled_time IS NOT NULL AND scheduled_time <= now()
	`)
	if err != nil {
		return 0, fmt.Errorf("dispatching scheduled jobs: %w", err)
	}
	return tag.RowsAffected(), nil
}

// ── Baseline resolution (docs/compliance/06-BASELINE.md §2) ───────────────

// AgentAttributes carries the scope-matching attributes of one agent:
// os_distro/os_version from the agents row plus the category/project names
// from its org-structure FKs. The spec's role/environment/datacenter/
// cluster/application have no dedicated columns (migration 008 dropped
// agents.scope as dead); the category name is the broad grouping
// ("Production", "Client A") and the project name the narrow division —
// the resolver aliases environment→category and application→project so
// those selector keys still work against the schema that exists.
type AgentAttributes struct {
	AgentID   uuid.UUID
	OsDistro  string
	OsVersion string
	Category  string
	Project   string
}

// ScopeAttrs projects the agent's attributes onto the scope matcher's input
// type — one converter instead of four identical struct literals scattered
// across ingest/policy/baseline.
func (a AgentAttributes) ScopeAttrs() scope.AgentAttributes {
	return scope.AgentAttributes{
		OsDistro: a.OsDistro, OsVersion: a.OsVersion,
		Category: a.Category, Project: a.Project,
	}
}

// LoadAgentAttributes fetches one agent's scope-matching attributes.
func (s *Store) LoadAgentAttributes(ctx context.Context, agentID uuid.UUID) (AgentAttributes, error) {
	var a AgentAttributes
	a.AgentID = agentID
	err := s.db.QueryRow(ctx, `
		SELECT COALESCE(a.os_distro, ''), COALESCE(a.os_version, ''),
		       COALESCE(c.name, ''), COALESCE(p.name, '')
		FROM agents a
		LEFT JOIN categories c ON c.id = a.category_id
		LEFT JOIN projects p ON p.id = a.project_id
		WHERE a.id = $1
	`, agentID).Scan(&a.OsDistro, &a.OsVersion, &a.Category, &a.Project)
	if err != nil {
		return AgentAttributes{}, fmt.Errorf("loading agent attributes for %s: %w", agentID, err)
	}
	return a, nil
}

// PublishedBaseline is one enabled baseline's PUBLISHED version with its
// scope metadata — the input set for effective-baseline resolution.
type PublishedBaseline struct {
	VersionID     uuid.UUID
	BaselineID    uuid.UUID
	ScopeType     string
	ScopeSelector map[string]any
	ExpectedState map[string]any
	PublishedAt   time.Time
}

// LoadPublishedBaselines returns every PUBLISHED version of an enabled
// baseline. BaselineService.publish deprecates the current PUBLISHED
// version before promoting a new one, so at most one row per baseline is
// live at a time — a flat list, not a window query.
func (s *Store) LoadPublishedBaselines(ctx context.Context) ([]PublishedBaseline, error) {
	rowsResult, err := s.db.Query(ctx, `
		SELECT bv.id, bv.baseline_id, b.scope_type, b.scope_selector, bv.expected_state, bv.published_at
		FROM baseline_versions bv
		JOIN baselines b ON b.id = bv.baseline_id
		WHERE bv.status = 'PUBLISHED' AND b.is_enabled = true
	`)
	if err != nil {
		return nil, fmt.Errorf("querying published baselines: %w", err)
	}
	defer rowsResult.Close()

	var out []PublishedBaseline
	for rowsResult.Next() {
		var p PublishedBaseline
		if err := rowsResult.Scan(&p.VersionID, &p.BaselineID, &p.ScopeType, &p.ScopeSelector, &p.ExpectedState, &p.PublishedAt); err != nil {
			return nil, fmt.Errorf("scanning published baseline row: %w", err)
		}
		out = append(out, p)
	}
	return out, rowsResult.Err()
}

// ListAgentIDs returns every registered agent's UUID — the recompute set
// for a COMPLIANCE_BASELINE_PUBLISHED fleet-wide invalidation
// (docs/compliance/06-BASELINE.md §2).
func (s *Store) ListAgentIDs(ctx context.Context) ([]uuid.UUID, error) {
	rowsResult, err := s.db.Query(ctx, `SELECT id FROM agents`)
	if err != nil {
		return nil, fmt.Errorf("querying agent ids: %w", err)
	}
	defer rowsResult.Close()

	var out []uuid.UUID
	for rowsResult.Next() {
		var id uuid.UUID
		if err := rowsResult.Scan(&id); err != nil {
			return nil, fmt.Errorf("scanning agent id row: %w", err)
		}
		out = append(out, id)
	}
	return out, rowsResult.Err()
}

// ListAgentAttributes bulk-loads every agent's scope-matching attributes —
// the input set for matching a compliance_assessments.scope_selector
// against the whole fleet in one query, never one LoadAgentAttributes call
// per agent (docs/compliance §38).
func (s *Store) ListAgentAttributes(ctx context.Context) ([]AgentAttributes, error) {
	rowsResult, err := s.db.Query(ctx, `
		SELECT a.id, COALESCE(a.os_distro, ''), COALESCE(a.os_version, ''),
		       COALESCE(c.name, ''), COALESCE(p.name, '')
		FROM agents a
		LEFT JOIN categories c ON c.id = a.category_id
		LEFT JOIN projects p ON p.id = a.project_id
	`)
	if err != nil {
		return nil, fmt.Errorf("listing agent attributes: %w", err)
	}
	defer rowsResult.Close()

	var out []AgentAttributes
	for rowsResult.Next() {
		var a AgentAttributes
		if err := rowsResult.Scan(&a.AgentID, &a.OsDistro, &a.OsVersion, &a.Category, &a.Project); err != nil {
			return nil, fmt.Errorf("scanning agent attributes row: %w", err)
		}
		out = append(out, a)
	}
	return out, rowsResult.Err()
}

// UpsertBaselineEffective materializes one agent's resolved effective
// baseline (docs/compliance/01-DATA-MODEL.md) — a cache, not a source of
// truth; safe to recompute and overwrite at any time.
func (s *Store) UpsertBaselineEffective(
	ctx context.Context,
	agentID uuid.UUID,
	versionIDs []uuid.UUID,
	mergedState map[string]any,
	mergedHash string,
) error {
	_, err := s.db.Exec(ctx, `
		INSERT INTO baseline_effective (agent_id, baseline_version_ids, merged_state, merged_hash, computed_at)
		VALUES ($1, $2, $3, $4, now())
		ON CONFLICT (agent_id) DO UPDATE
		SET baseline_version_ids = EXCLUDED.baseline_version_ids,
		    merged_state = EXCLUDED.merged_state,
		    merged_hash = EXCLUDED.merged_hash,
		    computed_at = now()
	`, agentID, versionIDs, mergedState, mergedHash)
	if err != nil {
		return fmt.Errorf("upserting baseline_effective (agent=%s): %w", agentID, err)
	}
	return nil
}

// GetBaselineEffective returns one agent's materialized merged_state, with
// found=false when no effective baseline has been computed for it yet.
func (s *Store) GetBaselineEffective(ctx context.Context, agentID uuid.UUID) (map[string]any, bool, error) {
	var mergedState map[string]any
	err := s.db.QueryRow(ctx, `
		SELECT merged_state FROM baseline_effective WHERE agent_id = $1
	`, agentID).Scan(&mergedState)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("loading baseline_effective for agent %s: %w", agentID, err)
	}
	return mergedState, true, nil
}

// ── Async fleet assessments (docs/compliance §24) ──────────────────────────

// Assessment is one compliance_assessments row's fields RunAssessment needs.
type Assessment struct {
	ID            uuid.UUID
	ScopeSelector map[string]any
	PolicySetID   *uuid.UUID
}

// ClaimNextPendingAssessment atomically picks the oldest PENDING assessment
// and flips it to RUNNING in one statement (SELECT ... FOR UPDATE SKIP
// LOCKED semantics aren't needed — only the elected leader ever calls this,
// scheduler.AssessmentPoller mirrors Dispatcher/Expirer's leader-only
// pattern), so there's no multi-writer race to guard against here. Returns
// found=false when there's nothing queued.
func (s *Store) ClaimNextPendingAssessment(ctx context.Context) (Assessment, bool, error) {
	var a Assessment
	err := s.db.QueryRow(ctx, `
		UPDATE compliance_assessments
		SET status = 'RUNNING', started_at = now()
		WHERE id = (
			SELECT id FROM compliance_assessments WHERE status = 'PENDING' ORDER BY created_at LIMIT 1
		)
		RETURNING id, scope_selector, policy_set_id
	`).Scan(&a.ID, &a.ScopeSelector, &a.PolicySetID)
	if errors.Is(err, pgx.ErrNoRows) {
		return Assessment{}, false, nil
	}
	if err != nil {
		return Assessment{}, false, fmt.Errorf("claiming next pending assessment: %w", err)
	}
	return a, true, nil
}

// SetAssessmentTotals records the resolved scope size once RunAssessment
// knows it (matched agent count, rule count for the target policy set) —
// separate from the initial claim since resolving scope requires a second
// query (ListAgentAttributes + selector matching) the claim itself doesn't do.
func (s *Store) SetAssessmentTotals(ctx context.Context, assessmentID uuid.UUID, serversTotal, rulesTotal int) error {
	_, err := s.db.Exec(ctx, `
		UPDATE compliance_assessments SET servers_total = $2, rules_total = $3 WHERE id = $1
	`, assessmentID, serversTotal, rulesTotal)
	if err != nil {
		return fmt.Errorf("setting assessment totals (id=%s): %w", assessmentID, err)
	}
	return nil
}

// IncrementAssessmentProgress bumps servers_done/rules_done — called once
// per agent (rulesDone = however many rules were actually evaluated for
// that agent) as RunAssessment works through the matched fleet, so a
// polling client sees live progress instead of only a final jump to 100%.
func (s *Store) IncrementAssessmentProgress(ctx context.Context, assessmentID uuid.UUID, serversDone, rulesDone int) error {
	_, err := s.db.Exec(ctx, `
		UPDATE compliance_assessments
		SET servers_done = servers_done + $2, rules_done = rules_done + $3
		WHERE id = $1
	`, assessmentID, serversDone, rulesDone)
	if err != nil {
		return fmt.Errorf("incrementing assessment progress (id=%s): %w", assessmentID, err)
	}
	return nil
}

// FinishAssessment marks an assessment COMPLETED or FAILED — the terminal
// transition RunAssessment always reaches, success or error, so no
// assessment is ever left stuck in RUNNING after a claim.
func (s *Store) FinishAssessment(ctx context.Context, assessmentID uuid.UUID, status string) error {
	_, err := s.db.Exec(ctx, `
		UPDATE compliance_assessments SET status = $2, completed_at = now() WHERE id = $1
	`, assessmentID, status)
	if err != nil {
		return fmt.Errorf("finishing assessment (id=%s, status=%s): %w", assessmentID, status, err)
	}
	return nil
}

// RulesForPolicySet returns every enabled rule in one policy set, across all
// its domains — RunAssessment groups these by Domain itself since the
// evaluator needs one domain's rules against that domain's latest snapshot
// at a time. Distinct from RulesForPolicySetsAndDomain (single-domain,
// scope-resolved multi-set) — this is single-set, all-domain, used only for
// the explicit policy_set_id an assessment targets.
func (s *Store) RulesForPolicySet(ctx context.Context, policySetID uuid.UUID) ([]RuleWithPolicySet, error) {
	rowsResult, err := s.db.Query(ctx, `
		SELECT cr.id, cr.rule_key, cr.check_source, cr.check_expr, cr.platform_filter,
		       cr.expected_value, cr.domain, psr.policy_set_id
		FROM compliance_rules cr
		JOIN policy_set_rules psr ON psr.rule_id = cr.id
		WHERE psr.policy_set_id = $1 AND cr.status = 'ACTIVE'
	`, policySetID)
	if err != nil {
		return nil, fmt.Errorf("querying rules for policy set %s: %w", policySetID, err)
	}
	defer rowsResult.Close()

	var out []RuleWithPolicySet
	var ruleIDs []uuid.UUID
	for rowsResult.Next() {
		var r RuleWithPolicySet
		var checkSource string
		var expectedValueJSON []byte
		if err := rowsResult.Scan(
			&r.Rule.ID, &r.RuleKey, &checkSource, &r.Rule.CheckExpr, &r.Rule.PlatformFilter,
			&expectedValueJSON, &r.Domain, &r.PolicySetID,
		); err != nil {
			return nil, fmt.Errorf("scanning policy set rule row: %w", err)
		}
		r.Rule.CheckSource = rules.CheckSource(checkSource)
		if len(expectedValueJSON) > 0 {
			if err := json.Unmarshal(expectedValueJSON, &r.Rule.ExpectedValue); err != nil {
				return nil, fmt.Errorf("decoding expected_value for rule %s: %w", r.RuleKey, err)
			}
		}
		id, err := uuid.Parse(r.Rule.ID)
		if err != nil {
			return nil, fmt.Errorf("rule %s has a non-UUID id: %w", r.RuleKey, err)
		}
		ruleIDs = append(ruleIDs, id)
		out = append(out, r)
	}
	if err := rowsResult.Err(); err != nil {
		return nil, err
	}

	evidencePaths, err := s.evidencePathsForRules(ctx, ruleIDs)
	if err != nil {
		return nil, err
	}
	for i := range out {
		out[i].Rule.EvidencePaths = evidencePaths[out[i].Rule.ID]
	}
	return out, nil
}
