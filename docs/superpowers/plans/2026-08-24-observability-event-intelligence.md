# Observability & Event Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform LokiLinux from disconnected observations into a correlated incident pipeline: `Observation → Event → Signal → Correlation → Incident → Runbook → Job → Agent`, without breaking any existing subsystem and without touching the Go agent in the MVP.

**Architecture:** New bounded contexts inside the existing FastAPI backend (`events/`, `signals/`, `correlation/`, `incidents/`, `topology/`, `runbooks/` packages) plus 3 new NATS workers wired into the existing `main.py` lifespan. PostgreSQL keeps operational state (signals, incidents, rules, topology, runbooks). ClickHouse (new core dependency) stores append-only event history, signal occurrences, and incident evidence with TTL retention. Redis holds correlation windows, dedup keys, rate limits. TimescaleDB metrics are untouched. Runbooks reuse the existing Workflow Engine v0.3.0 (compile-down to Jobs). Existing Alert pipeline stays intact; incidents additionally create Alerts via `AlertService`.

**Tech Stack:** FastAPI 0.138 / SQLAlchemy async / Alembic (existing) · ClickHouse 24.x via `clickhouse-connect` (new dep) · NATS core pub/sub + new JetStream stream utility · Redis 7.4 via existing `cache.py` patterns · Nuxt 4 pages/stores following existing conventions.

---

## 0. Verified current state (Phase-1 inspection results)

Facts confirmed against the live repo at `/opt/lokilinux`:

| Area | State | Evidence |
|---|---|---|
| Multi-tenancy | **None.** No `tenant_id` anywhere | grep across backend |
| ClickHouse | **Absent** from compose, backend, frontend | grep across repo |
| NATS topics | Single source of truth `backend/lokilinux/nats_topics.py`, ~14 subjects under `lokilinux.*`; plain-core subscribe (no JetStream streams managed in code) | `nats_topics.py`, `workers/*.py` |
| Alert pipeline | HeartbeatMonitorWorker(60s sweep) → `AGENT_UNHEALTHY` → AlertProcessorWorker → `AlertService.create_alert` (PG upsert dedup on partial index `uq_alerts_active_agent_type`) → `ALERT_CREATED` → NotificationWorker (SMTP/Slack). Frontend `/alerts` ack/resolve | `services/alert_service.py:30-81`, `workers/alert_processor.py` |
| Agent | Go static binary; 60s heartbeat carries system_status/packages(SHA256 delta)/vulns/health/domain_hashes(BLAKE3)/job_results/recent_logs; local SQLite; systemd-run job sandbox | `agent/internal/agent/manager.go`, docs §4 |
| gRPC servicer | `api/grpc/agent_service.py` calls `AgentService.update_heartbeat()`, relays compliance hashes/snapshots to NATS | verified |
| Workflow Engine v0.3.0 | `services/workflow_engine.py` compiles intent-steps → Jobs via JobService; approval/condition/notification/webhook nodes; `advance_run` from router + WorkflowRunnerWorker | file docstring |
| Workers wiring | 15 workers started in `main.py` lifespan block (~lines 85–130) | verified |
| Migrations | Alembic flat numbering, latest `0029_drop_dead_cve_count.py` | `backend/alembic/versions/` |
| Frontend | Nuxt 4 pages dir: account, admin, agents, alerts, auth, automation, compliance, jobs, plugins, policies, servers, vulnerabilities, workflows | `frontend/pages/` |

## 1. Locked architecture decisions

1. **No new microservice.** All bounded contexts live inside `backend/lokilinux/`. Correlation implemented in Python behind clean interfaces; hot path may move to Go later only if profiling demands.
2. **Tenant-ready schema:** every NEW table gets `tenant_id TEXT NOT NULL DEFAULT 'default'` and every new query filters on it. No refactor of existing tables. Cross-tenant correlation impossible by construction (tenant_id part of every group/fingerprint/window key).
3. **ClickHouse is a core dependency** (user decision): added to base docker-compose, required by API/workers.
4. **Raw events live ONLY in ClickHouse** (+ NATS for replay). PG never stores raw events. `GET /api/v1/events` queries ClickHouse.
5. **Signals are operational state in PG**: one row per `(tenant_id, fingerprint)` with `occurrence_count`, `first_seen/last_seen`. Raw occurrences appended to ClickHouse.
6. **Backward compatibility:** all existing subjects/APIs/pages untouched. Incident creation ALSO creates an Alert through the existing `AlertService.create_alert` (dedup included); additive nullable `alerts.incident_id` column links them.
7. **Runbook = thin mapping row** (`incident_type → workflow_id`), execution flows through existing WorkflowEngine → JobService → Agent. `AUTO` mode off by default (safe by default).
8. **Idempotency everywhere:** producer-generated UUID `event_id`; deterministic fingerprint SHA256(tenant|host|type|resource); Redis dedup SETEX 300s; PG upserts; all workers tolerate redelivery.
9. **Agent untouched in Phases A–F** (user decision "pipeline core first"). Agent batching/compression/policy = Phase G.

## 2. Data ownership contract

| Store | Owns | Never stores |
|---|---|---|
| PostgreSQL | signals (current), incidents, incident_signals, incident_timeline, correlation_rules, topology_nodes, topology_edges, runbooks, alerts(+incident_id) | raw events, metric samples |
| ClickHouse | events (raw+normalized), signal_occurrences, incident_evidence | incidents state, config, correlation state |
| TimescaleDB | existing agent_health/metrics hypertables (unchanged) | anything new |
| Redis | `ev:dedup:*`, `sig:thr:*`, `corr:{rule}:{grp}` ZSET windows, `rate:ev:*`, locks | source of truth of anything |
| NATS JetStream | EVENTS stream (`lokilinux.events.>`), SIGNALS (`lokilinux.signals.>`), INCIDENTS (`lokilinux.incidents.>`) — replay buffer | long-term storage |

## 3. Attachment points to existing code (do NOT duplicate these)

1. `api/grpc/agent_service.py` — after `update_heartbeat`: publish host heartbeat + metric.sample events.
2. `workers/heartbeat_monitor.py` — alongside AGENT_UNHEALTHY: publish `host.unreachable` event.
3. `workers/job_executor.py` — after `complete_job`: publish `job.completed` / `job.failed`.
4. `COMPLIANCE_DRIFT_DETECTED` subject (already published by compliance relay) — signal_processor consumes it directly → `compliance.violation`.
5. `services/alert_service.py::create_alert` — called by IncidentService (unchanged signature).
6. `services/workflow_engine.py` / workflow_service `start_run` — invoked by runbook matcher.
7. `main.py` lifespan — start 3 new workers; `api/v1/__init__.py` — include new routers.

---

## PHASE A — Foundation: ClickHouse + Event Model

### Task A1: ClickHouse service + client module

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `backend/pyproject.toml` (or requirements file used by backend Dockerfile)
- Create: `backend/lokilinux/ch.py`
- Test: `backend/tests/unit/test_ch_ddl.py`

- [ ] Add `clickhouse` service to `docker-compose.yml`: image `clickhouse/clickhouse-server:24.8-alpine`, env `CLICKHOUSE_USER/CLICKHOUSE_PASSWORD/CLICKHOUSE_DB=lokilinux`, volume `clickhouse_data:/var/lib/clickhouse`, mem_limit 2g, cpus 2, healthcheck `wget -qO- http://localhost:8123/ping`, networks `lokilinux-network`, port 8123 internal-only. Add volume `clickhouse_data`.
- [ ] Add to `.env.example`: `CLICKHOUSE_URL=http://clickhouse:8123`, `CLICKHOUSE_USER=default`, `CLICKHOUSE_PASSWORD=`, `CLICKHOUSE_DATABASE=lokilinux`, `EVENT_RETENTION_DAYS=30`, `SIGNAL_OCCURRENCE_RETENTION_DAYS=90`, `INCIDENT_EVIDENCE_RETENTION_DAYS=180`.
- [ ] Add `clickhouse-connect>=0.7` dependency; install in backend image build.
- [ ] Create `backend/lokilinux/ch.py`:
  - `get_ch()` singleton returning `clickhouse_connect.get_client(url=settings.CLICKHOUSE_URL, ...)`; all calls wrapped `asyncio.to_thread`.
  - `async def ensure_tables()` — idempotent DDL (IF NOT EXISTS):

```sql
CREATE TABLE IF NOT EXISTS events (
  timestamp DateTime64(3),
  event_id UUID,
  tenant LowCardinality(String),
  source LowCardinality(String),
  type LowCardinality(String),
  severity LowCardinality(String),
  host_id String,
  service String,
  fingerprint String,
  schema_version UInt8 DEFAULT 1,
  payload String DEFAULT ''
) ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (tenant, type, timestamp)
TTL toDateTime(timestamp) + INTERVAL %(event_retention)s DAY;

CREATE TABLE IF NOT EXISTS signal_occurrences (
  timestamp DateTime64(3),
  tenant LowCardinality(String),
  signal_type LowCardinality(String),
  severity LowCardinality(String),
  host_id String,
  service String,
  fingerprint String,
  value Float64 DEFAULT 0,
  metadata String DEFAULT ''
) ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (tenant, signal_type, timestamp)
TTL toDateTime(timestamp) + INTERVAL %(sig_retention)s DAY;

CREATE TABLE IF NOT EXISTS incident_evidence (
  timestamp DateTime64(3),
  tenant LowCardinality(String),
  incident_id UUID,
  kind LowCardinality(String),      -- signal | event | action
  ref String,                        -- fingerprint or event_id or job_id
  summary String
) ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (tenant, incident_id, timestamp)
TTL toDateTime(timestamp) + INTERVAL %(evidence_retention)s DAY;
```

- [ ] Unit test asserting DDL strings contain TTL/partition clauses and stay byte-stable (regression guard).
- [ ] Commit: `feat(infra): add ClickHouse service, client module, event store schema`

### Task A2: Event schemas + fingerprinting + NATS subjects

**Files:**
- Modify: `backend/lokilinux/nats_topics.py`
- Create: `backend/lokilinux/events/__init__.py`, `backend/lokilinux/events/schemas.py`, `backend/lokilinux/events/fingerprint.py`
- Modify: `backend/lokilinux/config.py`
- Test: `backend/tests/unit/test_event_schemas.py`, `backend/tests/unit/test_fingerprint.py`

- [ ] Append to `nats_topics.py`:

```python
# Observability pipeline
EVENT_RAW = "lokilinux.events.raw"            # + ".{source}" suffix per publish
EVENT_NORMALIZED = "lokilinux.events.normalized"
SIGNAL_DETECTED = "lokilinux.signals.detected"
SIGNAL_RESOLVED = "lokilinux.signals.resolved"
INCIDENT_CREATED = "lokilinux.incidents.created"
INCIDENT_UPDATED = "lokilinux.incidents.updated"
INCIDENT_RESOLVED = "lokilinux.incidents.resolved"
```

- [ ] `events/schemas.py`:

```python
ALLOWED_SOURCES = {"agent","metrics","security","compliance","patch","network","ansible","job","external","otel"}
SEVERITIES = ("DEBUG","INFO","WARNING","ERROR","CRITICAL")

class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    source: str                      # must be in ALLOWED_SOURCES
    type: str = Field(pattern=r"^[a-z0-9_.]{3,128}$")
    severity: str = "INFO"
    host_id: str | None = None
    service: str | None = None
    timestamp: datetime | None = None   # server-stamped when absent; rejected if skew > EVENT_MAX_CLOCK_SKEW_SEC
    payload: dict[str, Any] = Field(default_factory=dict)

class NormalizedEvent(EventIn):
    event_id: UUID          # generated server-side if absent
    tenant_id: str
    timestamp: datetime     # always set post-normalization
    fingerprint: str
```

- [ ] `events/fingerprint.py`: `def fingerprint(tenant_id, host_id, type_, resource) -> str` — `sha256("|".join(filter(None,[...]))).hexdigest()[:32]`; resource defaults to host_id or "". Tests: deterministic, excludes timestamp/randomness, distinct tenants differ.
- [ ] Validation tests: bad type pattern rejected, oversize payload rejected (payload serialized size > `EVENT_MAX_PAYLOAD_BYTES`), unknown source rejected, clock-skew rejection.
- [ ] `config.py` additions: `EVENT_MAX_PAYLOAD_BYTES:int=65536`, `EVENT_RATE_PER_AGENT_PER_MIN:int=600`, `EVENT_MAX_CLOCK_SKEW_SEC:int=300`, retention vars from A1, `CORRELATION_STATE_BACKEND="redis"`.
- [ ] Commit: `feat(events): event schema, deterministic fingerprints, pipeline NATS subjects`

### Task A3: Event repository (batched CH writes + cursor query)

**Files:**
- Create: `backend/lokilinux/events/repository.py`
- Test: `backend/tests/unit/test_event_repository.py`, integration `backend/tests/integration/test_ch_roundtrip.py`

- [ ] `EventRepository`:
  - internal `list[dict]` buffer + lock; `async def add(NormalizedEvent)` appends; flush when `len >= EVENT_INSERT_BATCH (1000)` or oldest buffered age > `EVENT_INSERT_FLUSH_SEC (1.0)`; flush uses one `insert` call per batch (column-oriented, no per-row inserts).
  - `on_flush_error`: log + re-buffer up to `EVENT_BUFFER_MAX (10_000)`; beyond that drop OLDEST DEBUG/INFO rows first, count into Prometheus `lokilinux_events_dropped_total`. Never drop ERROR/CRITICAL.
  - `async def query(tenant_id, type=None, source=None, host_id=None, since=None, until=None, limit=50, cursor=None) -> {items, next_cursor}` — parameterized CH SELECT ordered by (timestamp DESC).
- [ ] Integration test (requires running CH): insert 3 rows, query back by type filter; assert order + fields roundtrip.
- [ ] Commit: `feat(events): batched ClickHouse repository with bounded backpressure`

### Task A4: Ingestion endpoint + JetStream stream utility

**Files:**
- Modify: `backend/lokilinux/api/v1/__init__.py`
- Create: `backend/lokilinux/api/v1/routers/events.py`
- Create: `backend/lokilinux/eventbus.py`
- Test: `backend/tests/unit/test_events_router.py`

- [ ] `eventbus.py`: `async def ensure_streams(nc)` — JetStream manager creating durable streams if missing (idempotent): `EVENTS` (subjects `lokilinux.events.>`, `WorkQueuePolicy` not needed — use limits retention, max_age 24h replay buffer), `SIGNALS` (`lokilinux.signals.>`), `INCIDENTS` (`lokilinux.incidents.>`). Called once in lifespan. Plain-core subscribers unchanged (streams exist purely for replay/audit).
- [ ] `routers/events.py`:
  - `POST /api/v1/events` — auth: `get_current_user` OR agent mTLS identity header; accepts `EventIn` or `{"events": [EventIn, ...]}` (max 100/batch); derives `tenant_id='default'`; publishes JSON to `{EVENT_RAW}.{source}`; returns `{"accepted": n, "rejected": [{index, reason}]}`.
  - Rate limiting: Redis INCR `rate:ev:{principal}:{minutebucket}` EXPIRE 60, reject 429 over limit.
  - Payload size guard middleware-level check per event.
  - `GET /api/v1/events` — passthrough to `EventRepository.query` (JWT-authenticated read path over ClickHouse).
- [ ] Register router in `api/v1/__init__.py` following existing include_router style.
- [ ] Commit: `feat(api): external event ingestion + events query endpoint + JetStream streams`

### Task A5: Producers at attachment points + EventProcessorWorker

**Files:**
- Modify: `backend/lokilinux/api/grpc/agent_service.py` (post-heartbeat hook)
- Modify: `backend/lokilinux/workers/heartbeat_monitor.py`
- Modify: `backend/lokilinux/workers/job_executor.py`
- Create: `backend/lokilinux/workers/event_processor.py`
- Modify: `backend/lokilinux/main.py`
- Modify: `settings_schema.py` (flag `event_pipeline_enabled`, default true)
- Test: `backend/tests/unit/test_event_processor.py`, `backend/tests/unit/test_producers.py`

- [ ] Shared helper `backend/lokilinux/events/publish.py`: `async def emit(nats, source, type_, *, host_id=None, service=None, severity="INFO", payload=None)` — stamps tenant/timestamp/event_id, serializes once, publishes to `{EVENT_RAW}.{source}`; swallow-and-log on NATS failure (producers must never break their host flow — same policy as existing alert publish try/except).
- [ ] `agent_service.py` gRPC handler: after successful `update_heartbeat` → `emit("agent", "host.heartbeat.ok", host_id=str(agent.id))` + one `emit("metrics", "metric.sample", payload={"cpu":..., "memory":..., "disk":...})` per health dict present. Guarded by `event_pipeline_enabled` setting read via cached settings lookup.
- [ ] `heartbeat_monitor.py`: where AGENT_UNHEALTHY published → also `emit("agent", "host.unreachable", host_id=...)`.
- [ ] `job_executor.py`: after `complete_job` → `emit("job", "job.completed"|"job.failed", payload={"job_id":..., "exit_code":...})`.
- [ ] `event_processor.py` (`EventProcessorWorker`):
  - subscribes `lokilinux.events.raw.*`;
  - validate via `EventIn` → reject→metric;
  - dedup: SET NX `ev:dedup:{event_id}` EX 300 — skip if seen;
  - compute fingerprint; build `NormalizedEvent`;
  - `EventRepository.add(...)`; publish normalized JSON to `EVENT_NORMALIZED`;
  - Prometheus counters `lokilinux_events_received_total{source}`, `lokilinux_events_dropped_total{reason}`;
  - worker constructor/start pattern copied from `alert_processor.py` (nats client + session-free — this worker needs NO db).
- [ ] Wire into `main.py` lifespan after existing workers; respect flag.
- [ ] Tests: dedup skips second identical event_id; malformed JSON doesn't kill subscription loop (mirrors `_handle_unhealthy` try/except style); flag off → no publishes.
- [ ] Commit: `feat(pipeline): event producers at grpc/heartbeat/job points + event processor worker`

---

## PHASE B — Signal Engine

### Task B1: Signal model + migration 0030

**Files:**
- Create: `backend/alembic/versions/0030_signals_and_correlation_rules.py` (covers B1 + C1 tables in one revision)
- Create: `backend/lokilinux/signals/__init__.py`, `backend/lokilinux/signals/models.py`, `backend/lokilinux/signals/schemas.py`
- Test: migration runs up/down cleanly (`make migrate` in dev stack)

- [ ] Migration 0030 (down-revision 0029):

```python
op.create_table("signals",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
    sa.Column("type", sa.Text(), nullable=False),                 # cpu.high, service.failed ...
    sa.Column("severity", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False, server_default="OPEN"),  # OPEN|RESOLVED|SUPPRESSED
    sa.Column("host_id", postgresql.UUID(as_uuid=True)),
    sa.Column("service", sa.Text()),
    sa.Column("fingerprint", sa.Text(), nullable=False),
    sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_event_id", postgresql.UUID(as_uuid=True)),
    sa.Column("metadata", postgresql.JSONB, default={}),
    sa.UniqueConstraint("tenant_id", "fingerprint", name="uq_signals_tenant_fingerprint"),
    sa.Index("ix_signals_open", "status", "severity"),
)
op.create_table("correlation_rules",
    sa.Column("id", ...uuid pk...),
    sa.Column("tenant_id", ..., server_default="default"),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("enabled", sa.Boolean(), server_default=sa.true()),
    sa.Column("window_seconds", sa.Integer(), nullable=False, server_default="300"),
    sa.Column("group_by", postgresql.JSONB, nullable=False),        # ["host_id"] etc
    sa.Column("conditions", postgresql.JSONB, nullable=False),      # [{"signal":"cpu.high","weight":20}, ...]
    sa.Column("threshold_score", sa.Integer(), nullable=False),
    sa.Column("incident_type", sa.Text(), nullable=False),
    sa.Column("incident_severity", sa.Text(), nullable=False),
    sa.Column("suppressions", postgresql.JSONB, default=[]),        # maintenance windows
    sa.Column("version", sa.Integer(), server_default="1"),
    sa.Column("created_by", postgresql.UUID(as_uuid=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.UniqueConstraint("tenant_id", "name", name="uq_corr_rules_tenant_name"),
)
```

- [ ] `signals/models.py` SQLAlchemy models matching above, following existing model style (see `models/alert.py`).
- [ ] Verify: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` clean in dev.
- [ ] Commit: `feat(signals): signals + correlation_rules tables (migration 0030)`

### Task B2: Detectors + SignalService + SignalProcessorWorker

**Files:**
- Create: `backend/lokilinux/signals/detectors.py`, `backend/lokilinux/signals/service.py`, `backend/lokilinux/signals/repository.py`
- Create: `backend/lokilinux/workers/signal_processor.py`
- Modify: `backend/lokilinux/main.py`
- Test: `backend/tests/unit/test_detectors.py`, `backend/tests/unit/test_signal_service.py`

- [ ] `detectors.py` — registry mapping normalized event type → detector callable returning `DetectedSignal(type, severity, host_id, service, resource, value) | None`:

| Input event | Detector | Output signal |
|---|---|---|
| `host.unreachable` | direct | `host.unreachable` CRITICAL |
| `host.heartbeat.ok` | recovery hook | resolves OPEN `host.unreachable` for that host (publishes SIGNAL_RESOLVED) |
| `job.failed` | direct | `job.failed` HIGH |
| `compliance.drift.detected` (consumed from existing subject) | severity map | `compliance.violation` (HIGH/CRITICAL if drift severity HIGH/CRITICAL) |
| `metric.sample` | threshold+sustain | `cpu.high` (≥90 two consecutive samples), `memory.high` (≥90×2), `disk.usage.high` (≥90 once) — sustain counters in Redis `sig:thr:{host}:{metric}` INCR EXPIRE 600 |

- Thresholds configurable later via settings; constants module-level now.
- [ ] `signal_service.py::upsert_signal(detected, event)`:
  - fingerprint = `fingerprint(tenant, host_id, sig_type, resource)`;
  - `INSERT ... ON CONFLICT (tenant_id,fingerprint) DO UPDATE SET occurrence_count = signals.occurrence_count+1, last_seen=EXCLUDED.last_seen, severity=GREATEST-by-rank(severity, EXCLUDED.severity), status='OPEN' RETURNING` (single statement, race-safe);
  - CH `signal_occurrences` insert via repository buffer;
  - publish `SIGNAL_DETECTED` with `{signal_id, type, severity, host_id, fingerprint, occurrence_count, group hints}`.
- [ ] `signal_processor.py` (`SignalProcessorWorker`): subscribes `EVENT_NORMALIZED` AND `COMPLIANCE_DRIFT_DETECTED` (second callback wraps drift payload into normalized event shape); applies detectors; calls service. DB access via session factory like other workers.
- [ ] Tests: sustain logic (1 sample below threshold no signal; 2nd triggers), occurrence_count increments on same fingerprint, recovery resolves unreachable, drift severity mapping.
- [ ] Commit: `feat(signals): detectors, dedup/upsert signal service, signal processor worker`

---

## PHASE C — Correlation Engine

### Task C1: Rule evaluator + Redis window + suppression

**Files:**
- Create: `backend/lokilinux/correlation/__init__.py`, `evaluator.py`, `rules.py`, `suppression.py`
- Create: `backend/lokilinux/workers/correlation_worker.py`
- Modify: `backend/lokilinux/main.py`
- Test: `backend/tests/unit/test_correlation_evaluator.py`, `test_suppression.py`

- [ ] `evaluator.py`:
  - `async def on_signal(sig) -> list[IncidentCandidate]`;
  - load enabled rules filtered by membership of `sig.type` in conditions (in-memory rule cache refreshed ≤30s, keyed by updated max(version));
  - for each matching rule: `group_key = sha256(rule.id|tenant|join(group_by values))`;
  - Redis: `ZADD corr:{rule_id}:{group_key} {now_ms} {sig.type}` then `EXPIRE window_seconds`; score = Σ weights of DISTINCT member types still in window (Z RANGE scan);
  - suppression check (time-window entries `[{"from":"Sat 00:00","to":"Sun 23:59"}]` simple cron-ish ranges v1);
  - score ≥ threshold_score → candidate `{rule, group_key, member_types, score, root_signal=highest-weight member}` guarded by Redis `SETNX lock:corr:{rule}:{group}` EX 5 to prevent double-fire on redelivery.
- [ ] Tenant isolation invariant: tenant_id embedded in group_key and window key — unit test proving tenant A/B same hosts never share a window.
- [ ] Seed fixture: constant `DEFAULT_RULE_APPLICATION_DEGRADATION` (cpu.high w20, load.high w20, http.latency.high w25, http.error_rate.high w35; threshold 60; window 300s; group_by ["host_id"]; incident_type `application_degradation`; severity CRITICAL) exposed via CLI/settings bootstrap insert-if-absent.
- [ ] `correlation_worker.py`: subscribes `SIGNAL_DETECTED` → `on_signal` → hands candidates to IncidentService (Phase D import — stub interface now `IncidentSink.open(candidate)`; wire real impl in Task D2).
- [ ] Commit: `feat(correlation): weighted window evaluator, redis state, suppression, worker`

---

## PHASE D — Incident Engine + Alert compat

### Task D1: Incident models + migration 0031

**Files:**
- Create: `backend/alembic/versions/0031_incidents_and_alert_link.py`
- Create: `backend/lokilinux/incidents/__init__.py`, `models.py`, `schemas.py`
- Test: migration up/down

- [ ] Tables:

```python
"incidents": id pk uuid, tenant_id default 'default', title Text, type Text, severity Text,
  status Text default 'OPEN',           # OPEN|ACKNOWLEDGED|IN_PROGRESS|RESOLVED|CLOSED
  root_cause_signal_id uuid null FK signals.id,
  confidence Float,                     # clamp(score/threshold, 0..1)
  group_key Text,                       # index — reopen/dedup lookups
  correlation_rule_id uuid null FK correlation_rules.id,
  started_at, updated_at, resolved_at, acknowledged_at,
  metadata JSONB,
  Index ix_incidents_open (tenant_id, status)

"incident_signals": incident_id FK, signal_id FK, primary key(incident_id, signal_id)
"incident_timeline": id pk, incident_id FK index, ts timestamptz, kind Text,  # created|signal|transition|runbook|note
  message Text, payload JSONB

ALTER TABLE alerts ADD COLUMN incident_id UUID NULL REFERENCES incidents(id)
```

- [ ] Models mirroring `models/alert.py` conventions.
- [ ] Commit: `feat(incidents): incident/relations/timeline tables + alerts.incident_id link (migration 0031)`

### Task D2: IncidentService lifecycle

**Files:**
- Create: `backend/lokilinux/incidents/service.py`, `lifecycle.py`, `timeline.py`
- Modify: `backend/lokilinux/workers/correlation_worker.py` (replace sink stub)
- Test: `backend/tests/unit/test_incident_lifecycle.py`, `test_incident_service.py`

- [ ] `lifecycle.py`: `TRANSITIONS = {"OPEN":{"ACKNOWLEDGED","IN_PROGRESS","RESOLVED"}, "ACKNOWLEDGED":{"IN_PROGRESS","RESOLVED"}, "IN_PROGRESS":{"RESOLVED"}, "RESOLVED":{"CLOSED","OPEN"}, "CLOSED":set()}` — illegal transition raises `ValueError`; RESOLVED→OPEN recorded in timeline as `REOPENED`.
- [ ] `IncidentService.open_from_candidate(candidate)`:
  - dedup guard: existing incident same `(tenant_id, group_key)` with status in OPEN/ACKNOWLEDGED/IN_PROGRESS → attach signal to it instead (incident_signals insert ON CONFLICT DO NOTHING) + timeline entry; return existing;
  - else INSERT incident (title from rule.incident_type + top host, root_cause=root signal, confidence=score/threshold clamped), link ALL member signals, seed timeline rows (one per contributing signal, chronological);
  - **backward-compat bridge:** call `AlertService(db, nats).create_alert(title=f"Incident: {title}", severity=incident_severity, alert_type="INCIDENT", description=..., )` then set that alert's `incident_id` (update) — existing /alerts page + NotificationWorker keep working unmodified;
  - publish `INCIDENT_CREATED`; CH `incident_evidence` rows (kind=signal per member);
  - idempotent under redelivery: unique-ish guard via `lock:inc:{group_key}` SETNX during open.
- [ ] `ack(id,user)`, `resolve(id,user)`, `reopen(signal)` methods with transitions + timeline + `INCIDENT_UPDATED`/`INCIDENT_RESOLVED` publishes.
- [ ] Auto-resolution helper `maybe_auto_resolve(incident_id)`: all linked signals RESOLVED and quiet ≥ `INCIDENT_AUTO_RESOLVE_QUIET_SEC (600)` → resolve with timeline note. Invoked from incident_worker sweep.
- [ ] Tests: lifecycle legality matrix; double-open collapses into one incident + signal attached; alert created exactly once per NEW incident; reopen flow.
- [ ] Commit: `feat(incidents): lifecycle service with alert bridge, dedup, auto-resolve`

### Task D3: Incident worker (watcher + sweeper)

**Files:**
- Create: `backend/lokilinux/workers/incident_worker.py`
- Modify: `backend/lokilinux/main.py`
- Test: `backend/tests/unit/test_incident_worker.py`

- [ ] Subscribes `SIGNAL_RESOLVED` → for each OPEN incident containing that fingerprint → `maybe_auto_resolve`.
- [ ] Asyncio sweep loop (pattern copy of `job_timeout.py`): every 60s scan OPEN incidents whose signals all stale → resolve.
- [ ] Commit: `feat(incidents): incident watcher/sweeper worker`

---

## PHASE E — Topology + Runbooks

### Task E1: Topology models, resolver, API

**Files:**
- Create: `backend/alembic/versions/0032_topology.py`
- Create: `backend/lokilinux/topology/{__init__,models,service}.py`
- Create: `backend/lokilinux/api/v1/routers/topology.py` (register in `__init__.py`)
- Test: `backend/tests/unit/test_topology_resolver.py`

- [ ] Tables: `topology_nodes(id, tenant_id, kind HOST|SERVICE|APPLICATION|EXTERNAL, name, agent_id UUID NULL FK agents, UNIQUE(tenant_id,kind,name))`; `topology_edges(from_node FK, to_node FK, kind default 'DEPENDS_ON', PRIMARY KEY(from_node,to_node))`.
- [ ] Auto-seed: on `host.heartbeat.ok` processing (signal_processor hook) ensure HOST node exists named by agent hostname (INSERT ON CONFLICT DO NOTHING — cheap).
- [ ] Resolver: recursive CTE (depth cap 5) `upstream(node) -> dependency closure` and `downstream(node) -> impact set`; used by correlation candidate enrichment: if root signal has node → annotate candidate with upstream names as probable cause context (metadata only; does not override weight-based root_cause).
- [ ] Router: GET graph (nodes+edges), POST node, POST edge, DELETE edge — `require_role("ADMIN","OPERATOR")` for mutations.
- [ ] Commit: `feat(topology): nodes/edges, recursive resolver, REST CRUD`

### Task E2: Runbooks (workflow bridge)

**Files:**
- Create: `backend/alembic/versions/0033_runbooks.py`
- Create: `backend/lokilinux/runbooks/{__init__,models,service}.py`, `backend/lokilinux/api/v1/routers/runbooks.py`
- Modify: `backend/lokilinux/workers/incident_worker.py` (matcher hook)
- Modify: `frontend` nav (Phase F does UI; here only backend)
- Test: `backend/tests/unit/test_runbook_matcher.py`

- [ ] Table: `runbooks(id, tenant_id, name, incident_type Text, workflow_id FK workflows NULL, trigger_mode Text 'MANUAL'|'AUTO', min_severity Text, enabled bool, created_by, created_at, UNIQUE(tenant_id, incident_type, name))`.
- [ ] Matcher in incident_worker on INCIDENT_CREATED: enabled runbook where `incident_type` matches AND severity rank ≥ min_severity:
  - AUTO → call existing workflow start path (same entrypoint the workflows router uses) targeting hosts from incident_signals → timeline entry kind=runbook with run id;
  - MANUAL → nothing automatic; surfaced in API/UI for one-click launch.
  - Global kill switch setting `incident_autorun_runbooks` default false — AUTO no-ops while false (safe by default).
- [ ] Router: standard CRUD + `POST /api/v1/runbooks/{id}/execute {incident_id}` manual trigger.
- [ ] Commit: `feat(runbooks): incident→workflow bridge with safe-by-default auto trigger`

---

## PHASE F — API surface + minimal UI

### Task F1: Remaining routers

**Files:**
- Create: `backend/lokilinux/api/v1/routers/incidents.py`, `signals.py`, `correlation.py`, `observability.py`
- Modify: `backend/lokilinux/api/v1/__init__.py`
- Test: router smoke tests per existing patterns

- [ ] `incidents.py`: GET `/incidents` (filters status/severity/type, cursor pagination), GET `/{id}` (with signals + last N timeline), POST `/{id}/ack|resolve|reopen` (`require_role ADMIN,OPERATOR`), GET `/{id}/timeline`, GET `/{id}/evidence` (CH query by incident_id).
- [ ] `signals.py`: GET `/signals` (status/severity/type/host filters), POST `/{id}/resolve`, POST `/{id}/suppress`.
- [ ] `correlation.py`: GET/POST/PATCH/DELETE `/correlation/rules` (validate conditions JSON shape: each entry signal∈known registry ∪ freeform, weight int>0; threshold>0; window 30–3600).
- [ ] `observability.py`: GET `/observability/pipeline` — snapshot from prometheus_client registry (received/dropped rates, worker liveness timestamps, CH insert latency gauge, queue depths).
- [ ] Self-metrics additions wherever produced: `lokilinux_signals_detected_total`, `lokilinux_incidents_created_total`, `lokilinux_correlation_duration_seconds` (histogram around evaluator), `lokilinux_clickhouse_insert_errors_total`, `lokilinux_agent_queue_depth` (repo buffer len).
- [ ] Commit: `feat(api): incidents/signals/correlation/observability endpoints`

### Task F2: Frontend — Incidents (primary view)

**Files:**
- Create: `frontend/pages/incidents/index.vue`, `frontend/pages/incidents/[id].vue`
- Create: `frontend/stores/incidents.ts`
- Modify: `frontend/layouts/default.vue` (nav entry)

- [ ] List page: DataTable columns severity/status/title/type/started_at; badge colors reusing `useSeverity()`; actions ack/resolve mirroring `pages/alerts/index.vue` interaction pattern (acting ref, toast errors).
- [ ] Detail page answers WHAT/WHY/AFFECTED/EVIDENCE: header badges (severity/status/confidence %), root-cause card (signal type + host + evidence link), affected hosts/services chips from incident_signals, vertical timeline component (ts + kind icon + message), expandable raw-evidence section querying `/incidents/{id}/evidence`, runbook panel (available runbooks for type; Execute button when MANUAL).
- [ ] Pinia store fetch actions following `stores/jobs.ts` style (cursor pagination).
- [ ] Commit: `feat(ui): incidents list + detail with timeline, root cause, runbook panel`

### Task F3: Frontend — Signals, Events, Topology, Correlation Rules, Runbooks

**Files:**
- Create: `frontend/pages/signals/index.vue`, `frontend/pages/events/index.vue`, `frontend/pages/topology/index.vue`, `frontend/pages/correlation/index.vue`, `frontend/pages/runbooks/index.vue`
- Create matching Pinia stores; modify `layouts/default.vue` nav group "Observability"

- [ ] Signals: table type/severity/host/occurrences/first-last seen/status; resolve/suppress actions.
- [ ] Events: read-only paged table over GET /events with type/source filter; explicitly secondary UI (expandable rows).
- [ ] Topology: simple list-based editor v1 (node select + depends-on target; SVG graph deferred).
- [ ] Correlation: rules table + create/edit dialog validating weights/threshold client-side; enable/disable toggle.
- [ ] Runbooks: table incident_type→workflow select, trigger_mode radio (MANUAL default), min_severity, enabled.
- [ ] Commit: `feat(ui): observability suite pages (signals/events/topology/correlation/runbooks)`

---

## PHASE G — Deferred (post-MVP; specified, not scheduled)

### G1. OpenTelemetry ingestion
- `POST /api/v1/otlp/v1/logs` + `/traces` accepting OTLP HTTP protobuf (`content-type: application/x-protobuf`) using `opentelemetry-proto` package; logs → events(source="otel"); traces → stored as trace-ref events (trace_id/span_id/service/timestamp) usable as incident evidence references. No span-storage engine.

### G2. Agent optimization (hard budgets enforced by benchmarks)
- New agent package `internal/eq`: bounded ring queue (default 10k), priority classes CRITICAL/HIGH/NORMAL/LOW (drop LOW first, NEVER CRITICAL security/job-state), gzip batch, flush on 100 events OR 256KB OR 1s (config flags mirror spec §22 defaults).
- Proto: add `rpc ReportEvents(stream EventBatch) returns (EventAck)` to `proto/lokilinux.proto` + hand-written struct in `agent/gen/lokilinux/` + Python servicer consuming batches → publishes to `{EVENT_RAW}.{source}` preserving event_ids (idempotent end-to-end).
- Policy pull via existing proto `SyncPolicy` RPC: collectors on/off + intervals + thresholds (spec §26), agent reports `policy_version`.
- Benchmarks (`go test -bench ./internal/...` + runtime gauges exported): scenarios idle / normal / 100 ev/min / 1000 ev/min / network outage / recovery. Budget gates: CPU <0.5% avg idle, RSS <50MB, goroutine count stable. Fail CI if regression vs baseline file.

### G3. Load & failure testing
- `scripts/load_events.py` (asyncio publisher, ramp profiles 1K/10K/100K eps).
- Failure matrix integration tests: NATS redelivery duplicates → zero dup incidents; CH down → events buffer-drop policy engages, incident lifecycle unaffected (PG path independent); Redis down → correlation fails open (each high-severity signal opens its own incident rather than silently dropping — documented degradation); Postgres blip → NATS retention replays.

## Rollout & rollback

1. Deploy order: `docker compose pull && up -d clickhouse` → `alembic upgrade head` (migrate container) → restart api/grpc.
2. Kill switches (platform settings KV, checked by workers each loop): `event_pipeline_enabled=false` stops event_processor/signal/correlation/incident workers cleanly; legacy alerting continues independently.
3. Rollback = flip flag + optionally `docker compose stop clickhouse` (API degrades: /events endpoints return 503, everything else normal).
4. Retention enforcement: CH TTL handles pruning automatically; verify with `system.parts` size checks after 48h.

## Spec coverage cross-check

| Spec section | Where covered |
|---|---|
| §2–§3 minimal agent + final pipeline | Decisions 9/G2 |
| §4 data ownership | Section 2 contract |
| §5–§8 event/signal/fingerprint models | Tasks A2, B1–B2 |
| §9–§10 processor + NATS | Tasks A4–A5, nats_topics additions |
| §11–§14 correlation/windows/rules/topology | Phase C, E1 |
| §15–§16 incident lifecycle/timeline | Tasks D1–D3 |
| §17 alerts not broken | Decision 6 + D2 bridge (tested) |
| §18 compliance as signal source | B2 detector row (drift→compliance.violation) |
| §19 runbook via jobs | E2 (Workflow engine reused, zero duplication) |
| §20 OTel | G1 |
| §21 ClickHouse impl rules | A1 DDL (partition/TTL/order-by/batched inserts) |
| §22–§26 agent protocol/backpressure/policy | G2 |
| §27–§28 security/tenancy | A4 rate limits + validation; decision 2 tenant-ready |
| §29–§30 failure modes/idempotency | G3 matrix + dedup design throughout |
| §31 self-observability | F1 metrics list |
| §32–§34 structure/go-python/migrations | decisions 1, migrations 0030–0033 |
| §35–§37 API/UI principles | Phase F |
| §38 retention | A1 TTLs + rollout step 4 |
| §40–§41 testing | per-task tests + G2/G3 |
| §42–§44 principles/safety | Sections 1, 3; phases ordered analysis→code |
