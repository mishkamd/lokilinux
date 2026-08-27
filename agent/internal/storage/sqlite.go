// Package storage provides the local SQLite cache for offline operation.
//
// Uses modernc.org/sqlite (pure Go, CGO_ENABLED=0 compatible).
// Schema supports 30-day offline operation: job queue, packages cache,
// and key-value config store.
package storage

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	_ "modernc.org/sqlite" // register "sqlite" driver
)

const schema = `
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    job_type    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'PENDING',
    parameters  TEXT,              -- JSON
    created_at  INTEGER NOT NULL,  -- Unix epoch
    updated_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL   -- purge after 30 days
);

CREATE TABLE IF NOT EXISTS packages_cache (
    agent_id    TEXT NOT NULL,
    name        TEXT NOT NULL,
    version     TEXT NOT NULL,
    arch        TEXT,
    checksum    TEXT,              -- SHA256 of full list, stored once per snapshot
    cached_at   INTEGER NOT NULL,
    PRIMARY KEY (agent_id, name, version)
);

CREATE TABLE IF NOT EXISTS agent_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_state (
    domain       TEXT PRIMARY KEY,
    last_hash    TEXT NOT NULL,
    last_run_at  INTEGER NOT NULL,
    facts        TEXT
);

CREATE TABLE IF NOT EXISTS seen_jobs (
    nonce     TEXT PRIMARY KEY,
    job_id    TEXT NOT NULL,
    seen_at   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_seen_jobs_seen_at ON seen_jobs(seen_at);

CREATE INDEX IF NOT EXISTS idx_jobs_status    ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_expires   ON jobs(expires_at);
CREATE INDEX IF NOT EXISTS idx_pkgs_agent     ON packages_cache(agent_id);
`

// Store is the local SQLite cache.
type Store struct {
	db *sql.DB
}

// Open opens (or creates) the SQLite database at path.
func Open(path string) (*Store, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("open sqlite %s: %w", path, err)
	}
	// single writer — no WAL mode needed at this scale
	db.SetMaxOpenConns(1)

	if _, err := db.Exec(schema); err != nil {
		db.Close()
		return nil, fmt.Errorf("apply schema: %w", err)
	}
	return &Store{db: db}, nil
}

// Close releases the database handle.
func (s *Store) Close() error { return s.db.Close() }

// ---- Job queue ---------------------------------------------------------------

// MarkJobSeen records a replay-protection nonce. Returns false when the
// nonce was already present — the caller must then reject the job as a
// duplicate (INSERT OR IGNORE semantics, single statement = race-free).
func (s *Store) MarkJobSeen(ctx context.Context, nonce, jobID string) (bool, error) {
	res, err := s.db.ExecContext(ctx,
		`INSERT OR IGNORE INTO seen_jobs(nonce, job_id, seen_at) VALUES(?,?,?)`,
		nonce, jobID, time.Now().Unix(),
	)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	return n == 1, nil
}

// PruneSeenJobs drops replay entries older than cutoff. The retention window
// must exceed the longest envelope lifetime the platform can issue
// (expires_at - issued_at), otherwise an expired-but-unseen job could be
// replayed after its nonce is pruned.
func (s *Store) PruneSeenJobs(ctx context.Context, cutoff time.Time) error {
	_, err := s.db.ExecContext(ctx,
		`DELETE FROM seen_jobs WHERE seen_at < ?`, cutoff.Unix())
	return err
}

// PurgeExpiredJobs removes jobs older than 30 days.
func (s *Store) PurgeExpiredJobs(ctx context.Context) error {
	_, err := s.db.ExecContext(ctx,
		`DELETE FROM jobs WHERE expires_at < ?`, time.Now().Unix(),
	)
	return err
}

// ---- Config store ------------------------------------------------------------

// SetConfig stores a key-value pair.
func (s *Store) SetConfig(ctx context.Context, key, value string) error {
	_, err := s.db.ExecContext(ctx,
		`INSERT OR REPLACE INTO agent_config(key, value, updated_at) VALUES(?,?,?)`,
		key, value, time.Now().Unix(),
	)
	return err
}

// GetConfig retrieves a value by key; returns ("", nil) if not found.
func (s *Store) GetConfig(ctx context.Context, key string) (string, error) {
	var value string
	err := s.db.QueryRowContext(ctx,
		`SELECT value FROM agent_config WHERE key=?`, key,
	).Scan(&value)
	if err == sql.ErrNoRows {
		return "", nil
	}
	return value, err
}

// ---- Config store ------------------------------------------------------------

// ComplianceState is one domain's last-collected snapshot, persisted so an
// agent restart doesn't lose lastHash/lastRun — internal/compliance.Runner
// reads this on startup (docs/compliance/03-AGENT-PLUGIN-SDK.md §6) to
// avoid re-sending domain_full for domains that haven't actually changed
// since before the restart.
type ComplianceState struct {
	Domain    string
	LastHash  string
	LastRunAt time.Time
	Facts     string // canonical JSON, "" if not yet captured
}

// UpsertComplianceState stores the latest collected state for one domain.
func (s *Store) UpsertComplianceState(ctx context.Context, domain, hash, facts string) error {
	_, err := s.db.ExecContext(ctx,
		`INSERT OR REPLACE INTO compliance_state(domain, last_hash, last_run_at, facts) VALUES(?,?,?,?)`,
		domain, hash, time.Now().Unix(), facts,
	)
	return err
}

// AllComplianceState loads every persisted domain state, for Runner to warm
// its in-memory cache from on startup.
func (s *Store) AllComplianceState(ctx context.Context) ([]ComplianceState, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT domain, last_hash, last_run_at, facts FROM compliance_state`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var states []ComplianceState
	for rows.Next() {
		var st ComplianceState
		var ts int64
		if err := rows.Scan(&st.Domain, &st.LastHash, &ts, &st.Facts); err != nil {
			return nil, err
		}
		st.LastRunAt = time.Unix(ts, 0)
		states = append(states, st)
	}
	return states, rows.Err()
}
