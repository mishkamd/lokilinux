---
title: "Observability & Critical Signal Layer — implementation plan"
date: 2026-08-23
type: feature
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
---

# Observability & Critical Signal Layer — implementation plan

## Summary

LokiLinux gains an enterprise **Critical Signal Detection** layer: the agent detects operationally important signals (kernel panics, OOM, filesystem errors, service failures, auth failures) directly at the source — journald native severity filtering and incremental file tailing — matches them with a single-pass Aho-Corasick matcher, normalizes them into a versioned taxonomy, deduplicates and rate-limits locally, spools to disk when offline, and ships compressed batches over the existing mTLS gRPC channel. The control plane validates, authenticates, quota-limits, stores into **ClickHouse** (new, decisions taken), correlates into existing Alerts, exposes query APIs, and renders an Observability UI. TimescaleDB remains metrics-only (its dead `agent_metrics` hypertable gets activated). PostgreSQL stays state/config only.

Decisions locked with the product owner: ClickHouse from phase 2; gRPC transport (existing channel) + REST for external/OTel; correlation on existing Alerts; journald via persistent `journalctl -f` follower (CGO=0 constraint); incidents/runbooks do not exist yet — provider interfaces defined now, engines later.

## Problem Frame

- **In scope:** ClickHouse infra + schema; ingestion API (gRPC + REST); agent signal detector pipeline; spool/batching/compression; signal policy push via heartbeat delta; alerts correlation; Observability frontend; OTel detection stub; docs; tests incl. failure/perf.
- **Out of scope:** general-purpose logging; Kafka/Elastic/Fluent Bit; full OTel collector management; Incident engine build-out; Runbook engine; AI providers implementation.
- **Hard constraints:** agent stays CGO_ENABLED=0 static; RAM 30–70MB / CPU <1% budget; zero public ClickHouse exposure; no breaking changes to heartbeat contract (additive fields only).

## Requirements

- R1: Agent transmits only matched critical signals — never full logs; severity pre-filter as close to source as possible (journald `-p err..alert`).
- R2: File sources read incrementally with inode+offset persistence surviving restart and rotation/truncate/recreate without full re-read.
- R3: One-pass keyword matching (Aho-Corasick), dictionary driven by server-pushed policy (versioned), not hardcoded.
- R4: Local aggregation `{count, first_seen, last_seen, samples≤3}` per fingerprint per window; token-bucket rate limits per signal type from policy.
- R5: Bounded memory channel + bounded zstd disk spool (`/var/lib/lokilinux/spool`, default cap 512MB) with replay on recovery; drops counted, never blocking the host.
- R6: Batches ≤500 records / 5s flush; transport = new `IngestObservability(stream)` RPC reusing the mTLS connection; REST `POST /api/v1/observability/ingest` exists for OTel/generic producers.
- R7: Ingestion validates taxonomy/severity/sizes, derives identity from the mTLS certificate (never trusts payload ids), enforces Redis quotas, returns ack counts.
- R8: ClickHouse holds only high-volume append-only data (4 MergeTree tables, monthly partitions, TTL 180/90/365/config days); PG holds policies/state only; TimescaleDB holds metrics only.
- R9: Signals correlate into existing Alerts grouped by fingerprint+host within window (occurrences pattern).
- R10: Frontend Observability section (Overview, Critical Signals) + host detail tab, admin-friendly terminology, polling conventions.
- R11: Interfaces exist for future consumers: `IncidentAnalysisProvider` (RuleBased impl), compliance evidence adapter note, OTel detection stub.
- R12: Failure matrix tested (API down, CH down, storm, corrupt line, rotation, restart, spool full) + perf harness proving budgets at 10k/100k lines/sec.

## Key Technical Decisions

- KTD1: **journalctl follower, not sdjournal** — libsystemd bindings break the static CGO=0 build; a single persistent `journalctl -f -p err..alert -o json --show-cursor [--after-cursor]` child process achieves native severity+cursor filtering; supervisor restarts it with capped backoff; cursor persisted in SQLite per source.
- KTD2: **Aho-Corasick via cloudflare/ahocorasick (pure Go)** — one pass per line; policy swap rebuilds the automaton atomically (pointer swap).
- KTD3: **Fingerprint = sha256(host_id ∥ signal_type ∥ normalized_message)** where normalization collapses whitespace and strips volatile numbers (PIDs, addresses). Aggregation window 60s keyed by fingerprint.
- KTD4: **Policy rides the existing heartbeat delta** — response gains `signal_policy{version, keywords[], rate_limits[], sources[]}` sent only when version changes (same pattern as policy delta); initial pull via extended `SyncPolicy`. No second config channel.
- KTD5: **Identity from certificate, not payload** — servicer resolves agent_id from TLS peer; mismatching payload agent_id ⇒ rejection counted in ack.
- KTD6: **SignalStore interface + ClickHouse impl** (`clickhouse-connect` HTTP) so an alternative store can be added later without touching handlers; queries use keyset pagination `(timestamp, fingerprint)`.
- KTD7: **ClickHouse schema applied by init.sql mounted into the official image's docker-entrypoint-initdb.d**, versioned in git; later alterations via numbered files + documented manual apply (no ORM for CH).
- KTD8: **Alerts grouping mirrors drift occurrences**: open alert per (host, fingerprint) inside window; new occurrence increments count instead of creating rows.
- KTD9: **Metrics activation is additive**: agent opt-in `metrics.enabled`; batches piggyback on the same IngestObservability stream (`metrics` map) written by `metrics_writer.py` into the existing hypertable; ReportMetrics proto stays unused (documented) to avoid two metric paths.
- KTD10: **All agent limits are config-capped and code-enforced**: bounded chan(1024), batch caps, spool ceiling, token buckets, dial timeouts, backoff ceiling 5m.

## Current State Reference (verified)

| Fact | Location |
|---|---|
| Servicer implements only HeartbeatStream | `backend/lokilinux/api/grpc/agent_service.py:64-70` |
| Generic JSON RPC handler | `backend/lokilinux/grpc_server.py:29-44,64` |
| Dead `agent_metrics` hypertable | `backend/alembic/versions/001_initial_schema.py:426-452` |
| JSON codec registered as „proto" | `agent/internal/communication/grpc_client.go:23-34` |
| Lazy shared connection | `grpc_client.go:44-70` |
| Heartbeat response handling (delta patterns) | `agent/internal/agent/manager.go:332-403` |
| SQLite store + purge | `agent/internal/storage/sqlite.go`, `manager.go runPurge` |
| Config sections + defaults | `agent/internal/config/config.go:10-104` |
| Router mounting table | `backend/lokilinux/api/v1/__init__.py:29-45` |
| NATS topics registry | `backend/lokilinux/nats_topics.py` |
| Alert processing worker | `backend/lokilinux/workers/alert_processor.py`, router `routers/alerts.py` |
| Compose service template | `docker-compose.yml` (healthcheck/deploy/internal-network blocks) |

## Implementation Units

### U1 — Phase 1: Analysis document

**Goal:** The mandated pre-code architecture analysis lives in-repo.
**Status:** DONE — `docs/architecture/observability-analysis.md` (14 sections, verified references).

### U2 — Phase 2: ClickHouse infrastructure

**Goal:** ClickHouse running internally with versioned schema; backend able to connect.
**Requirements:** R8
**Dependencies:** none
**Files:**
- `docker-compose.yml` — add `clickhouse` service (clickhouse/clickhouse-server:24.8-alpine, internal network only, volume `clickhouse_data`, healthcheck wget /ping, deploy 2CPU/2G), mount `./scripts/clickhouse/init.sql:ro` into docker-entrypoint-initdb.d; add `condition: service_healthy` dependency to `lokilinux-api` and `lokilinux-grpc`.
- `.env.example` — `CLICKHOUSE_USER/PASSWORD/URL=http://clickhouse:8123`.
- `scripts/clickhouse/init.sql` [NEW] — database `lokilinux`; tables per KTD6/§R8:
  - `critical_signals(timestamp DateTime64(3), tenant_id LowCardinality(String) DEFAULT 'default', host_id UUID, source/category/signal_type LowCardinality(String), severity Enum8('warning'=1,'critical'=2), count UInt32 DEFAULT 1, first_seen, last_seen, fingerprint FixedString(64), message String, samples Array(String)) ENGINE=MergeTree PARTITION BY toYYYYMM(timestamp) ORDER BY (tenant_id, host_id, signal_type, timestamp) TTL timestamp + INTERVAL 180 DAY`
  - `critical_logs` (raw matched lines, TTL 90 DAY, ORDER BY (tenant_id, host_id, timestamp))
  - `operational_events` (TTL 365 DAY)
  - `audit_events` (TTL configurable — header comment documents the ALTER)
- `backend/pyproject.toml` — add `clickhouse-connect`.
- `backend/lokilinux/core/settings` equivalents — `CLICKHOUSE_URL/USER/PASSWORD` settings fields.

**Verification:** `make up` → all healthchecks green; `docker compose exec clickhouse clickhouse-client --query "SHOW TABLES FROM lokilinux"` lists 4 tables.

### U3 — Phase 3: Backend ingestion (proto, gRPC servicer, REST, store, policies)

**Goal:** Signals accepted, validated, stored, queryable; policies manageable.
**Requirements:** R6, R7, R8
**Dependencies:** U2
**Files:**
- `proto/lokilinux.proto` — add `SignalRecord`, `ObservabilityBatch{agent_id, repeated SignalRecord signals, map<string,double> metrics}`, `IngestAck{success, accepted, rejected, error}`, `service ObservabilityService { rpc IngestObservability(stream ObservabilityBatch) returns (IngestAck); }`; run `make proto`.
- `backend/lokilinux/api/grpc/observability_service.py` [NEW] — `ObservabilityServicer.IngestObservability`: identity from TLS peer (KTD5), Pydantic validation (taxonomy enum, severity enum, count≥1, ≤500/batch, ≤8MB), Redis quota `rl:obs:{agent_id}` (60s window, settings cap), insert via store, publish `lokilinux.signal.detected` per aggregate, ack counts.
- `backend/lokilinux/grpc_server.py` — register second handler/route for `lokilinux.ObservabilityService/IngestObservability` wired with db_factory/cache/nats/store.
- `backend/lokilinux/services/observability/__init__.py`, `store.py` (Protocol), `clickhouse_store.py` (insert columnar batches; keyset pagination; overview aggregations; retry/backoff wrapper returning 503 semantics), `policies.py` (CRUD over model, version bump helper), `analysis.py` (`IncidentAnalysisProvider` Protocol + `RuleBasedAnalysisProvider` static recommendations per signal_type), `metrics_writer.py` (bulk write metrics map into `agent_metrics`).
- `backend/lokilinux/models/observability_policy.py` [NEW] + import in `models/__init__.py`; Alembic migration `0XX_add_observability_policies.py`.
- `backend/lokilinux/api/v1/routers/observability.py` [NEW]: `POST /ingest`, `GET /signals` (filters host/type/severity/source/since/until, keyset cursor), `GET /signals/{host_id}/{ts}/{fingerprint}`, `GET /overview` (Redis-cached 60s), `GET/PUT /policies` (ADMIN role). Mount in `api/v1/__init__.py` after line 45.
- `backend/lokilinux/nats_topics.py` — `SIGNAL_DETECTED = "lokilinux.signal.detected"`.

**Verification:** pytest contract suite (valid/invalid/mismatched-id/quota-exceeded); integration script inserting N signals then GET /signals pagination; `make proto` regenerates both languages cleanly.

### U4 — Phase 4: Agent detector

**Goal:** Source-to-signal pipeline inside the agent.
**Requirements:** R1–R4
**Dependencies:** none (can start parallel to U3)
**Files (all NEW under `agent/internal/signals/`):**
- `sources/journald_source.go` — spawn once: `journalctl -f -p err..alert -o json --show-cursor` (+ `--after-cursor` from state); parse JSON lines; supervise child (restart backoff 5s→5m); persist cursor per flush.
- `sources/file_source.go` — configured file list; stat-before-read; inode change→reopen@0; size<offset→truncate reset; partial-line carry buffer; persist inode+offset per flush.
- `state.go` — SQLite DDL additions in `internal/storage/sqlite.go`: `signal_sources_state(source PK, inode INTEGER, offset INTEGER, cursor TEXT)`; purge-aware.
- `matcher.go` — Aho-Corasick build/swap from policy; match→dict lookup.
- `taxonomy.go` — stable constants + version const: kernel.panic/kernel.fault/kernel.hardware_error/memory.oom/storage.io_error/storage.filesystem_error/storage.readonly/service.failed/security.authentication_failure/process.crash.
- `normalizer.go` + `fingerprint.go` — per KTD3.
- `aggregator.go` — 60s windows per fingerprint; samples≤3; token buckets per type from policy rate_limits.
- `pipeline.go` — bounded chan(1024); Stats counters {Scanned, Matched, Deduped, Dropped, Spooled, IngestFails}.
- `config.go` additions — `Signals SignalsConfig` + `Metrics MetricsConfig` sections per defaults (enabled true/false respectively).
- `manager.go` wiring — start sources+pipeline goroutines; extend `buildPayload` with `signal_policy_version`; extend `handleResponse` for `signal_policy` delta (KTD4).

**Verification:** go unit tests: AC goldens vs naive matcher; rotation matrix (rename/truncate/recreate) on t.TempDir files; aggregator window boundaries; journalctl JSON fixture parsing; cursor persistence across simulated restart.

### U5 — Phase 5: Spool, batching, compression, retry

**Goal:** No signal loss on outage; bounded resources enforced.
**Requirements:** R5, R6
**Dependencies:** U4 + U3 (transport target exists)
**Files:** `agent/internal/signals/spool.go` (segment files `sig-<seq>.zst`, 4MB max segment, 512MB ceiling, oldest-drop+counter), `agent/internal/signals/flusher.go` (≤500 rec/5s; replay spool first; backoff ceiling 5m; success deletes segments), `agent/internal/communication/observability_client.go` (second stub over existing lazy conn), `spool purge` hook in `runPurge`.

**Verification:** failure-mode tests — kill server mid-flight (spool grows, replay succeeds), spool-full drop accounting, storm generator (rate-limit holds), corrupted-line skip; `go test ./internal/signals/... -race`.

### U6 — Phase 6: Policy push end-to-end

**Goal:** Keyword/policy changes reach agents without redeploy.
**Requirements:** R3
**Dependencies:** U3+U4
**Files:** policies service (U3) publishing version; servicer includes `signal_policy` in heartbeat response when stale (compare versions table); frontend minimal policy editor page `pages/observability/policies.vue`.

**Verification:** E2E — edit policy keyword via API → within one heartbeat interval agent log shows matcher rebuild; new keyword detected in test log line.

### U7 — Phase 7: Alerts correlation

**Goal:** Storms become single grouped alerts.
**Requirements:** R9
**Dependencies:** U3
**Files:** `workers/alert_processor.py` — subscribe SIGNAL_DETECTED; rule matching extension `source_type="signal"`; grouping key `(agent, fingerprint)` open-alert update (count++, last_seen) mirroring drift occurrences; `docs/modules/02-control-plane.md` worker table row.

**Verification:** integration test — 200 OOM signals → exactly 1 open alert with count≥200; resolve path intact.

### U8 — Phase 8: Frontend

**Goal:** Enterprise Observability section.
**Requirements:** R10
**Dependencies:** U3
**Files:** `stores/observability.ts`, `pages/observability/index.vue` (Overview: totals card, by-severity 24h, top hosts, recent signals), `pages/observability/signals.vue` (filterable table + detail drawer with samples), `components/observability/SeverityBadge.vue`, tab in `pages/servers/[id].vue`, nav entries (Events/OpenTelemetry marked „soon").

**Verification:** vitest store tests; smoke script navigating filters; empty/loading states.

### U9 — Phase 9: Performance & security review

**Goal:** Prove budgets; harden boundaries.
**Requirements:** R12
**Files:** `agent/internal/signals/bench/main.go` [NEW] (synthetic 10k/100k lines/sec through pipeline, mem/CPU/alloc report), security checklist doc section (replay protection via cursor+timestamp sanity, payload caps, quota keys), review notes appended to analysis doc.

**Verification:** bench output committed under `docs/architecture/observability-analysis.md#performance`; no budget regression vs §35 targets.

### U10 — Phase 10: Documentation set

**Goal:** Ops/dev discoverability.
**Files:** `docs/architecture/observability.md` (this layer overview), `clickhouse.md` (schema, TTLs, backup/upgrade ops), `critical-signals.md` (taxonomy, policy format, matching rules), `otel.md` (detection stub, REST contract for future collectors), `docs/modules/11-observability.md` (module doc joining the series), index/README links.

## Testing strategy

Unit (Go): matcher/tailer/aggregator/spool/fingerprint matrices. Unit (Py): validation, quota, store mocks, policy versioning. Integration: compose profile `observability` — synthetic writer → ingest → CH assertions → alert grouping → API pagination. Failure: U5/U9 matrix. Perf: U9 bench gates. Regression: existing suites green each phase boundary (`go test ./...` both modules, `pytest tests/unit -q`, `npm test`).

## Compatibility & Rollout

Additive only: new proto service, new router prefix, new compose service, new agent config section with safe defaults (`signals.enabled=true` gated further by presence of sources; `metrics.enabled=false`). Heartbeat contract extended with optional fields — old servers ignore, new servers tolerate absence. Rollback: revert agent flags (`signals.enabled=false`) stops pipeline; compose service removable independently; no destructive migrations.
