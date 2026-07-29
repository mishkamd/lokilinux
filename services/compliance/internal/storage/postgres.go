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
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/lokilinux/compliance/internal/rules"
)

type Store struct {
	pool *pgxpool.Pool
}

// Open connects using databaseURL and verifies connectivity with a ping —
// a misconfigured DATABASE_URL should fail at startup, not on the first
// real query.
func Open(ctx context.Context, databaseURL string) (*Store, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("creating pgx pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("pinging database: %w", err)
	}
	return &Store{pool: pool}, nil
}

func (s *Store) Close() { s.pool.Close() }

// UpsertInventoryBlob stores the canonical body once per content_hash
// (docs/compliance/01-DATA-MODEL.md §3, D3) — a second write of the same
// hash increments ref_count instead of duplicating storage.
func (s *Store) UpsertInventoryBlob(ctx context.Context, contentHash string, body []byte, algo string) error {
	_, err := s.pool.Exec(ctx, `
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
	err := s.pool.QueryRow(ctx, `
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
	err = s.pool.QueryRow(ctx, `
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
	err := s.pool.QueryRow(ctx, `SELECT body FROM inventory_blobs WHERE content_hash = $1`, contentHash).Scan(&body)
	if err != nil {
		return nil, fmt.Errorf("fetching blob body %s: %w", contentHash, err)
	}
	return body, nil
}

// InsertDriftEvent records one drift.Event as a drift_events row plus one
// drift_details row per field diff — both hypertables (migration 017).
func (s *Store) InsertDriftEvent(
	ctx context.Context,
	agentID uuid.UUID,
	domain, comparedAgainst, severity, changeType, summary string,
	fieldDiffs []DriftFieldDiff,
) (uuid.UUID, error) {
	now := time.Now().UTC()
	var eventID uuid.UUID
	err := s.pool.QueryRow(ctx, `
		INSERT INTO drift_events (time, agent_id, domain, compared_against, severity, change_type, summary)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		RETURNING id
	`, now, agentID, domain, comparedAgainst, severity, changeType, summary).Scan(&eventID)
	if err != nil {
		return uuid.Nil, fmt.Errorf("inserting drift event (agent=%s domain=%s): %w", agentID, domain, err)
	}

	for _, d := range fieldDiffs {
		_, err := s.pool.Exec(ctx, `
			INSERT INTO drift_details (time, drift_event_time, drift_event_id, field_path, old_value, new_value)
			VALUES ($1, $2, $3, $4, $5, $6)
		`, now, now, eventID, d.FieldPath, d.OldValue, d.NewValue)
		if err != nil {
			return eventID, fmt.Errorf("inserting drift detail %s for event %s: %w", d.FieldPath, eventID, err)
		}
	}
	return eventID, nil
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

// ActiveRulesForDomain returns enabled CEL/OVAL_UNMAPPED/OSCAP_FALLBACK
// rules for a domain that belong to a globally-assigned policy set.
//
// ponytail: GLOBAL-scope assignments only — full scope-tree resolution
// (matching an agent's os/role/environment/datacenter/cluster/application
// against policy_assignments.scope_selector, the same merge-by-specificity
// algorithm baseline_effective uses) is real, non-trivial logic that
// doesn't exist yet anywhere in this service. This is the honest v1: an
// org with only fleet-wide policy sets gets correct evaluation today;
// scoped assignments are silently not applied until that resolver is
// built. Upgrade path: replace this query with a call into a
// baseline.Resolver-shaped PolicyResolver once that exists.
func (s *Store) ActiveRulesForDomain(ctx context.Context, domain string) ([]RuleWithPolicySet, error) {
	rowsResult, err := s.pool.Query(ctx, `
		SELECT DISTINCT cr.id, cr.rule_key, cr.check_source, cr.check_expr, psr.policy_set_id
		FROM compliance_rules cr
		JOIN policy_set_rules psr ON psr.rule_id = cr.id
		JOIN policy_assignments pa ON pa.policy_set_id = psr.policy_set_id
		WHERE cr.domain = $1 AND cr.is_enabled = true
		  AND pa.is_enabled = true AND pa.scope_type = 'GLOBAL'
	`, domain)
	if err != nil {
		return nil, fmt.Errorf("querying active rules for domain %s: %w", domain, err)
	}
	defer rowsResult.Close()

	var out []RuleWithPolicySet
	for rowsResult.Next() {
		var r RuleWithPolicySet
		var checkSource string
		if err := rowsResult.Scan(&r.Rule.ID, &r.RuleKey, &checkSource, &r.Rule.CheckExpr, &r.PolicySetID); err != nil {
			return nil, fmt.Errorf("scanning active rule row: %w", err)
		}
		r.Rule.CheckSource = rules.CheckSource(checkSource)
		out = append(out, r)
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
}

// InsertRuleEvaluation records one verdict. rule_evaluations is a hypertable
// (migration 016) — every call is a plain INSERT, never an UPDATE.
func (s *Store) InsertRuleEvaluation(
	ctx context.Context,
	agentID, ruleID, policySetID uuid.UUID,
	result string,
	actualValue, evidence []byte,
	errMsg string,
) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO rule_evaluations (time, agent_id, rule_id, policy_set_id, result, actual_value, evidence, error_message)
		VALUES ($1, $2, $3, $4, $5, $6, $7, NULLIF($8, ''))
	`, time.Now().UTC(), agentID, ruleID, policySetID, result, actualValue, evidence, errMsg)
	if err != nil {
		return fmt.Errorf("inserting rule evaluation (agent=%s rule=%s): %w", agentID, ruleID, err)
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
	tag, err := s.pool.Exec(ctx, `
		UPDATE jobs SET status = 'QUEUED', updated_at = now()
		WHERE status = 'SCHEDULED' AND scheduled_time IS NOT NULL AND scheduled_time <= now()
	`)
	if err != nil {
		return 0, fmt.Errorf("dispatching scheduled jobs: %w", err)
	}
	return tag.RowsAffected(), nil
}
