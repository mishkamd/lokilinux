<!-- generated-by: claude -->
# Data Model — PostgreSQL Schema

Migration `backend/alembic/versions/014_add_compliance.py`, `revision = "014"`,
`down_revision = "013"` (current head, per `013_add_agent_health_totals.py`). Follows the
conventions in every existing migration/model: UUID PK via `server_default=text("gen_random_uuid()")`
for top-level entities, `Integer` autoincrement PK for log/join tables, `String(50)` for status
columns instead of native `PG ENUM` (routers compare `.value` directly, see `models/policy.py:25`
comment), `created_by`/`changed_by`/`approved_by` as bare `UUID` **without** an FK (Better Auth
owns users, not this schema), no `relationship()` anywhere — every join is explicit
`select(...).join(...)` in the service layer. Every new model is registered in
`backend/lokilinux/models/__init__.py` or Alembic autogenerate silently ignores it.

## 1. Extensions

```sql
-- Already present (migration 001): pgcrypto, pg_trgm, timescaledb
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector, new for this module (10-AI.md RAG)
```

## 2. Baseline Manager

```sql
CREATE TABLE baselines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    scope_type      VARCHAR(20) NOT NULL,   -- GLOBAL/OS/ROLE/ENVIRONMENT/DATACENTER/CLUSTER/APPLICATION
    scope_selector  JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {"os_distro":"ol","os_version":"9","role":"database"}
    parent_baseline_id UUID REFERENCES baselines(id),
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    created_by      UUID,                    -- Better Auth user, no FK
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_baselines_scope_type ON baselines(scope_type);
CREATE INDEX ix_baselines_scope_selector_gin ON baselines USING GIN (scope_selector);
CREATE INDEX ix_baselines_parent ON baselines(parent_baseline_id);

CREATE TABLE baseline_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    baseline_id     UUID NOT NULL REFERENCES baselines(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'DRAFT',  -- DRAFT/PENDING_APPROVAL/APPROVED/PUBLISHED/DEPRECATED
    -- Expected state, one JSONB document per domain (see 03-AGENT-PLUGIN-SDK.md domain list)
    expected_state  JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash    VARCHAR(64) NOT NULL,     -- BLAKE3 over canonical expected_state
    signature       BYTEA,                    -- Ed25519 signature over content_hash, set on PUBLISHED
    signed_by       UUID,
    change_summary  TEXT,
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ,
    deprecated_at   TIMESTAMPTZ,
    UNIQUE (baseline_id, version)
);
CREATE INDEX ix_baseline_versions_baseline_status ON baseline_versions(baseline_id, status);
CREATE INDEX ix_baseline_versions_content_hash ON baseline_versions(content_hash);

CREATE TABLE baseline_approvals (
    id              SERIAL PRIMARY KEY,
    baseline_version_id UUID NOT NULL REFERENCES baseline_versions(id) ON DELETE CASCADE,
    approver_id     UUID NOT NULL,
    decision        VARCHAR(20) NOT NULL,   -- APPROVED/REJECTED
    comment         TEXT,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_baseline_approvals_version ON baseline_approvals(baseline_version_id);

-- Materialized "which baseline versions apply to this agent, merged" — computed by
-- lokilinux-compliance (02-GO-SERVICE.md), cached, invalidated on baseline publish/agent
-- attribute change. Not a source of truth — recomputable from baselines + baseline_versions.
CREATE TABLE baseline_effective (
    agent_id            UUID PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    baseline_version_ids UUID[] NOT NULL,   -- ordered least→most specific, for audit/explain
    merged_state        JSONB NOT NULL,
    merged_hash          VARCHAR(64) NOT NULL,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 3. Inventory Collector (content-addressable, D3)

```sql
CREATE TABLE inventory_blobs (
    content_hash    VARCHAR(64) PRIMARY KEY,   -- BLAKE3 of the canonical (pre-compression) body
    body            BYTEA NOT NULL,            -- zstd-compressed canonical JSON
    algo            VARCHAR(20) NOT NULL DEFAULT 'blake3',
    size_bytes       INTEGER NOT NULL,
    ref_count        INTEGER NOT NULL DEFAULT 1,   -- maintained by ingest upsert; gc when 0
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE inventory_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    domain          VARCHAR(50) NOT NULL,   -- 'kernel','sshd','sysctl','users','mounts', ... (03-AGENT-PLUGIN-SDK.md)
    content_hash    VARCHAR(64) NOT NULL REFERENCES inventory_blobs(content_hash),
    taken_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Immutable: never UPDATE a row, only INSERT the next snapshot. "Current" = latest per (agent_id, domain).
CREATE INDEX ix_inv_snapshots_agent_domain_time ON inventory_snapshots(agent_id, domain, taken_at DESC);
CREATE UNIQUE INDEX ix_inv_snapshots_dedup ON inventory_snapshots(agent_id, domain, content_hash, taken_at);

-- Delta history — one row per domain change (content_hash A -> B), hypertable for volume.
CREATE TABLE inventory_deltas (
    time            TIMESTAMPTZ NOT NULL,
    agent_id        UUID NOT NULL,
    domain          VARCHAR(50) NOT NULL,
    prev_hash       VARCHAR(64),
    new_hash        VARCHAR(64) NOT NULL,
    diff            JSONB,              -- computed unified diff of the two canonical documents
    PRIMARY KEY (time, agent_id, domain)
);
SELECT create_hypertable('inventory_deltas', 'time', if_not_exists => TRUE,
                          partitioning_column => 'agent_id', number_partitions => 16);
CREATE INDEX ix_inv_deltas_agent_time ON inventory_deltas(agent_id, time DESC);
ALTER TABLE inventory_deltas SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id');
SELECT add_compression_policy('inventory_deltas', INTERVAL '7 days');
SELECT add_retention_policy('inventory_deltas', INTERVAL '90 days');
```

## 4. Compliance Policy Engine

```sql
CREATE TABLE compliance_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_key        VARCHAR(255) NOT NULL UNIQUE,   -- e.g. "xccdf_org.ssgproject.content_rule_sshd_disable_root_login"
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    rationale       TEXT,
    severity        VARCHAR(20) NOT NULL,   -- LOW/MEDIUM/HIGH/CRITICAL (SSG severity, normalized)
    domain          VARCHAR(50) NOT NULL,   -- matches inventory domain this rule reads
    check_source    VARCHAR(20) NOT NULL DEFAULT 'CEL',  -- CEL / OVAL_UNMAPPED / OSCAP_FALLBACK
    check_expr      TEXT,                    -- CEL expression, NULL if OVAL_UNMAPPED
    expected_value  JSONB,                   -- human-readable expected value for the UI diff view
    platform_filter JSONB NOT NULL DEFAULT '[]'::jsonb,  -- CPE-derived applicability, e.g. ["rhel9","ol9","rocky9"]
    standard_refs   JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {"cis":["5.2.8"],"stig":["RHEL-09-255025"],"nist":["AC-6"],"pci":["2.2.4"]} — named standard_refs, not "references" (reserved word in PostgreSQL)
    remediation_template_id UUID,           -- FK added below, after remediation_templates exists
    source          VARCHAR(30) NOT NULL DEFAULT 'complianceascode',
    source_version  VARCHAR(50),             -- upstream content release tag, for reproducible imports
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_compliance_rules_domain ON compliance_rules(domain);
CREATE INDEX ix_compliance_rules_severity ON compliance_rules(severity);
CREATE INDEX ix_compliance_rules_standard_refs_gin ON compliance_rules USING GIN (standard_refs);
CREATE INDEX ix_compliance_rules_search ON compliance_rules USING GIN (title gin_trgm_ops);

CREATE TABLE remediation_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_key        VARCHAR(255) NOT NULL REFERENCES compliance_rules(rule_key),
    provider        VARCHAR(20) NOT NULL,   -- ansible/shell/python/terraform
    body            TEXT NOT NULL,          -- template source, {{ vars }} for policy-supplied params
    source          VARCHAR(30) NOT NULL DEFAULT 'complianceascode',
    git_path        VARCHAR(500),           -- path within the internal playbooks git repo, once promoted
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rule_key, provider, version)
);
ALTER TABLE compliance_rules
    ADD CONSTRAINT fk_compliance_rules_remediation
    FOREIGN KEY (remediation_template_id) REFERENCES remediation_templates(id);

CREATE TABLE policy_sets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,     -- "CIS Oracle Linux 9 Benchmark Level 2"
    slug            VARCHAR(100) NOT NULL UNIQUE,  -- "cis_ol9_l2"
    framework       VARCHAR(30) NOT NULL,      -- CIS/NIST/PCI_DSS/ISO27001/STIG/INTERNAL
    version         VARCHAR(50),
    description     TEXT,
    source_profile  VARCHAR(255),              -- upstream .profile id, if imported
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE policy_set_rules (
    policy_set_id   UUID NOT NULL REFERENCES policy_sets(id) ON DELETE CASCADE,
    rule_id         UUID NOT NULL REFERENCES compliance_rules(id) ON DELETE CASCADE,
    severity_override VARCHAR(20),
    PRIMARY KEY (policy_set_id, rule_id)
);

-- Which policy_set applies to which scope — mirrors baselines.scope_type/scope_selector
CREATE TABLE policy_assignments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_set_id   UUID NOT NULL REFERENCES policy_sets(id) ON DELETE CASCADE,
    scope_type      VARCHAR(20) NOT NULL,
    scope_selector  JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_policy_assignments_scope ON policy_assignments(scope_type);
CREATE INDEX ix_policy_assignments_selector_gin ON policy_assignments USING GIN (scope_selector);

-- Evaluation results — the highest-volume table in the module. One row per (agent, rule, run).
CREATE TABLE rule_evaluations (
    time            TIMESTAMPTZ NOT NULL,
    agent_id        UUID NOT NULL,
    rule_id         UUID NOT NULL,
    policy_set_id   UUID NOT NULL,
    result          VARCHAR(10) NOT NULL,   -- PASS/FAIL/ERROR/NOT_APPLICABLE/NOT_EVALUATED
    actual_value    JSONB,
    evidence        JSONB,                  -- raw fact snippet the check read, for the UI evidence panel
    error_message   TEXT,
    PRIMARY KEY (time, agent_id, rule_id, policy_set_id)
);
SELECT create_hypertable('rule_evaluations', 'time', if_not_exists => TRUE,
                          partitioning_column => 'agent_id', number_partitions => 16);
CREATE INDEX ix_rule_eval_agent_time ON rule_evaluations(agent_id, time DESC);
CREATE INDEX ix_rule_eval_rule_result ON rule_evaluations(rule_id, result);
ALTER TABLE rule_evaluations SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id');
SELECT add_compression_policy('rule_evaluations', INTERVAL '7 days');
SELECT add_retention_policy('rule_evaluations', INTERVAL '180 days');

-- Per-agent, per-category compliance score, one row per scan run.
CREATE TABLE compliance_scores (
    time            TIMESTAMPTZ NOT NULL,
    agent_id        UUID NOT NULL,
    category        VARCHAR(30) NOT NULL,   -- overall/security/configuration/filesystem/packages/kernel
    score           NUMERIC(5,2) NOT NULL,  -- 0.00-100.00
    passed_count    INTEGER NOT NULL,
    failed_count    INTEGER NOT NULL,
    not_applicable_count INTEGER NOT NULL,
    PRIMARY KEY (time, agent_id, category)
);
SELECT create_hypertable('compliance_scores', 'time', if_not_exists => TRUE,
                          partitioning_column => 'agent_id', number_partitions => 16);
ALTER TABLE compliance_scores SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id');
SELECT add_compression_policy('compliance_scores', INTERVAL '30 days');
SELECT add_retention_policy('compliance_scores', INTERVAL '2 years');

-- Continuous aggregates for fleet/cluster/environment/datacenter rollups (dashboard trend charts,
-- 11-FRONTEND.md). Refresh policy keeps these current without re-scanning raw rows.
CREATE MATERIALIZED VIEW compliance_scores_daily
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', time) AS day,
       agent_id, category,
       avg(score) AS avg_score,
       min(score) AS min_score
FROM compliance_scores
GROUP BY day, agent_id, category
WITH NO DATA;
SELECT add_continuous_aggregate_policy('compliance_scores_daily',
    start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
```

## 5. Configuration Drift Detection + File Integrity

```sql
CREATE TABLE drift_events (
    time            TIMESTAMPTZ NOT NULL,
    id              UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL,
    domain          VARCHAR(50) NOT NULL,
    compared_against VARCHAR(20) NOT NULL,  -- BASELINE/PREVIOUS_SNAPSHOT/DESIRED_STATE
    severity        VARCHAR(20) NOT NULL,   -- LOW/MEDIUM/HIGH/CRITICAL
    change_type     VARCHAR(30) NOT NULL,   -- FILE_CHANGED/PACKAGE_CHANGED/SERVICE_DISABLED/USER_ADDED/...
    summary         TEXT NOT NULL,
    changed_by_user VARCHAR(255),           -- best-effort from auditd/last-login correlation, nullable
    root_cause      JSONB,                  -- {"job_id":"...","source":"job"} | {"source":"unknown"}
    acknowledged_by UUID,
    acknowledged_at TIMESTAMPTZ,
    remediation_plan_id UUID,
    PRIMARY KEY (time, agent_id, id)   -- partitioning column (agent_id) must be part of the key
);
SELECT create_hypertable('drift_events', 'time', if_not_exists => TRUE,
                          partitioning_column => 'agent_id', number_partitions => 16);
CREATE INDEX ix_drift_events_agent_time ON drift_events(agent_id, time DESC);
CREATE INDEX ix_drift_events_severity ON drift_events(severity, time DESC);
ALTER TABLE drift_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id');
SELECT add_compression_policy('drift_events', INTERVAL '7 days');
SELECT add_retention_policy('drift_events', INTERVAL '365 days');

CREATE TABLE drift_details (
    time            TIMESTAMPTZ NOT NULL,
    drift_event_time TIMESTAMPTZ NOT NULL,
    drift_event_id  UUID NOT NULL,
    field_path      VARCHAR(500) NOT NULL,   -- JSON pointer into the domain document, e.g. "/sshd/PermitRootLogin"
    old_value       JSONB,
    new_value       JSONB,
    PRIMARY KEY (time, drift_event_id, field_path)
);
SELECT create_hypertable('drift_details', 'time', if_not_exists => TRUE);

CREATE TABLE file_hashes (
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    path            VARCHAR(1000) NOT NULL,
    algo            VARCHAR(10) NOT NULL DEFAULT 'sha256',   -- sha256/sha512/blake3
    hash            VARCHAR(128) NOT NULL,
    mode            INTEGER,
    uid             INTEGER,
    gid             INTEGER,
    size_bytes      BIGINT,
    mtime           TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, path)
);
CREATE INDEX ix_file_hashes_hash ON file_hashes(hash);   -- fleet-wide "who else has this exact file" lookup

CREATE TABLE file_changes (
    time            TIMESTAMPTZ NOT NULL,
    agent_id        UUID NOT NULL,
    path            VARCHAR(1000) NOT NULL,
    old_hash        VARCHAR(128),
    new_hash        VARCHAR(128),
    change_kind     VARCHAR(20) NOT NULL,   -- CREATED/MODIFIED/DELETED/PERMISSION_CHANGED
    PRIMARY KEY (time, agent_id, path)
);
SELECT create_hypertable('file_changes', 'time', if_not_exists => TRUE,
                          partitioning_column => 'agent_id', number_partitions => 16);
ALTER TABLE file_changes SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id');
SELECT add_compression_policy('file_changes', INTERVAL '7 days');
SELECT add_retention_policy('file_changes', INTERVAL '365 days');

-- Per-scope ignore rules so a known-noisy path (log rotation touching mtime, etc.) doesn't
-- generate perpetual drift events.
CREATE TABLE file_integrity_ignores (
    id              SERIAL PRIMARY KEY,
    scope_type      VARCHAR(20) NOT NULL DEFAULT 'GLOBAL',
    scope_selector  JSONB NOT NULL DEFAULT '{}'::jsonb,
    path_pattern    VARCHAR(1000) NOT NULL,   -- glob, matched agent-side before hashing
    reason          TEXT,
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 6. Remediation Engine

```sql
CREATE TABLE remediation_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'DRAFT',  -- DRAFT/PENDING_APPROVAL/APPROVED/EXECUTING/COMPLETED/FAILED/ROLLED_BACK
    trigger_type    VARCHAR(20) NOT NULL,    -- MANUAL/SCHEDULED/AUTOMATIC/AI_SUGGESTED
    maintenance_window_id UUID,
    is_emergency    BOOLEAN NOT NULL DEFAULT false,   -- bypasses maintenance-window gate, still requires approval unless auto-approve policy matches
    created_by      UUID,
    approved_by     UUID,
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE remediation_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remediation_plan_id UUID NOT NULL REFERENCES remediation_plans(id) ON DELETE CASCADE,
    rule_id         UUID REFERENCES compliance_rules(id),
    drift_event_id  UUID,
    agent_id        UUID NOT NULL,
    provider        VARCHAR(20) NOT NULL,   -- ansible/shell/python/terraform
    rendered_body   TEXT NOT NULL,          -- remediation_templates.body with vars substituted
    rollback_body   TEXT,
    sequence        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_remediation_actions_plan ON remediation_actions(remediation_plan_id);
CREATE INDEX ix_remediation_actions_agent ON remediation_actions(agent_id);

-- Join table to the existing Job Engine — one row per Job created from a plan (fan-out
-- already happens inside JobService; this just records which plan/actions a job serves).
CREATE TABLE remediation_jobs (
    remediation_plan_id UUID NOT NULL REFERENCES remediation_plans(id) ON DELETE CASCADE,
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    PRIMARY KEY (remediation_plan_id, job_id)
);

CREATE TABLE maintenance_windows (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    scope_type      VARCHAR(20) NOT NULL DEFAULT 'GLOBAL',
    scope_selector  JSONB NOT NULL DEFAULT '{}'::jsonb,
    cron_expr       VARCHAR(100),           -- recurring window, e.g. "0 2 * * SAT"
    duration_minutes INTEGER NOT NULL,
    timezone        VARCHAR(50) NOT NULL DEFAULT 'UTC',
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 7. AI Compliance Assistant

```sql
CREATE TABLE ai_recommendations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            VARCHAR(30) NOT NULL,   -- EXPLAIN_DRIFT/EXPLAIN_FAILURE/RISK_ESTIMATE/REMEDIATION_PLAN/PLAYBOOK/RCA/CHANGE_REQUEST/DOC
    status          VARCHAR(20) NOT NULL DEFAULT 'PROPOSED',  -- PROPOSED/APPROVED/REJECTED/APPLIED
    subject_type    VARCHAR(30),            -- drift_event/rule_evaluation/agent/fleet
    subject_id      UUID,
    prompt_context  JSONB,                  -- inputs the planner used, for reproducibility
    proposal        JSONB NOT NULL,         -- structured output: text, generated playbook/script, risk score
    model_provider  VARCHAR(30) NOT NULL,
    model_name      VARCHAR(100) NOT NULL,
    approved_by     UUID,
    approved_at     TIMESTAMPTZ,
    resulting_remediation_plan_id UUID REFERENCES remediation_plans(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_ai_recommendations_subject ON ai_recommendations(subject_type, subject_id);
CREATE INDEX ix_ai_recommendations_status ON ai_recommendations(status);

-- RAG corpus: internal docs, past RCAs, playbooks, policy text — chunked + embedded.
CREATE TABLE ai_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     VARCHAR(30) NOT NULL,   -- playbook/rca/policy/runbook/rule_doc
    source_id       UUID,
    title           VARCHAR(500),
    content_hash    VARCHAR(64) NOT NULL,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ai_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES ai_documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector(1536),           -- provider-dependent dimension, see 10-AI.md
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX ix_ai_chunks_embedding ON ai_chunks USING hnsw (embedding vector_cosine_ops);
```

## 8. Reporting Engine

```sql
CREATE TABLE compliance_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type     VARCHAR(30) NOT NULL,   -- FLEET_SUMMARY/POLICY_SET/DATACENTER/CUSTOM
    format          VARCHAR(10) NOT NULL,   -- PDF/CSV/XLSX/JSON
    params          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',  -- PENDING/GENERATING/COMPLETED/FAILED
    artifact_uri    VARCHAR(1000),          -- object storage path once COMPLETED
    generated_by    UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);
CREATE INDEX ix_compliance_reports_status ON compliance_reports(status);
```

## 9. Historical Audit — reuse, don't duplicate

No new audit table. This module writes to the **existing** `audit_logs` table
(`backend/lokilinux/models/audit.py`) through the **existing** `AuditService`
(`backend/lokilinux/services/audit_service.py:19`), which today is only called from
`routers/admin.py` — every compliance mutation (baseline publish, policy assignment,
remediation approval, AI recommendation approval) calls it too. `changes` JSONB carries
old/new value, matching the `admin.py:67-73` call shape.

Correction from an earlier draft of this document: `policy_audit` (`models/policy.py:37`) is
**not** activated by this module — its `policy_id` column has a hard FK to `policies.id`
(the legacy `Policy` model), and per [07-POLICY-ENGINE.md](07-POLICY-ENGINE.md) §6 this module
deliberately does not repurpose that table for `policy_sets`. Writing a `policy_sets.id` into
`policy_audit.policy_id` would violate the FK constraint outright. `policy_audit` remains
exactly what it was — a dormant table scoped to the legacy `Policy` model, unrelated to this
module. Policy-engine mutations (policy set create, rule add, assignment create) are audited
the same way baseline mutations are: through `AuditService`/`audit_logs`, not a dedicated table.

## 10. Registration

```python
# backend/lokilinux/models/__init__.py — additions
from .baseline import Baseline, BaselineVersion, BaselineApproval, BaselineEffective
from .inventory import InventoryBlob, InventorySnapshot, InventoryDelta
from .compliance_rule import ComplianceRule, RemediationTemplate, PolicySet, PolicySetRule, PolicyAssignment
from .rule_evaluation import RuleEvaluation, ComplianceScore
from .drift import DriftEvent, DriftDetail, FileHash, FileChange, FileIntegrityIgnore
from .remediation import RemediationPlan, RemediationAction, MaintenanceWindow
from .ai_compliance import AiRecommendation, AiDocument, AiChunk
from .compliance_report import ComplianceReport
```

## 11. Archival strategy

Continuous-aggregate rollups (`compliance_scores_daily`, plus equivalent monthly rollups for
`drift_events` and `rule_evaluations` counts) keep long-range dashboard trends cheap after raw
chunks age out. Once a chunk falls past its retention policy, TimescaleDB drops it; before
that, a nightly job (added to `RetentionCleanupWorker`, `backend/lokilinux/workers/retention_cleanup.py`,
which already runs an hourly sweep) exports chunks older than 30 days to Parquet in the
platform's configured object store (new `compliance.archive_bucket` setting in
`settings_schema.py`) before they're eligible for the TimescaleDB retention policy to drop
them — satisfying "need archive strategy" without inventing a second cleanup worker.
