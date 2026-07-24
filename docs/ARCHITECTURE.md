<!-- generated-by: gsd-doc-writer -->
# LokiLinux Architecture

LokiLinux is an enterprise Linux fleet management platform: centralized patch management,
vulnerability scanning, compliance automation, and remediation for large fleets (10K-100K+
Linux servers). A lightweight Go agent runs on every managed server and reports system state
over mTLS gRPC to a Python control plane; a Nuxt web UI drives policy, job orchestration, and
Ansible-based automation against the fleet.

The system is a layered, event-driven service mesh: a REST API and a gRPC server share the
same database and cache, coordinate through a NATS event bus, and hand off long-running work
to eight background workers.

## System overview

```
                        ┌─────────────────────┐
   Browser  ───────────▶│  lokilinux-frontend  │  Nuxt 4 + Vue 3, Better Auth (port 3000)
                        └──────────┬───────────┘
                                   │ /api/v1 (same-origin proxy, opaque bearer token)
                                   ▼
                        ┌─────────────────────┐
                        │    lokilinux-api     │  FastAPI REST (8000) + Prometheus (9090)
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                     ▼
      ┌───────────────┐   ┌───────────────┐     ┌────────────────┐
      │  pgbouncer →   │   │     Redis     │     │      NATS       │
      │  TimescaleDB   │   │  (cache-aside)│     │  (JetStream)     │
      └───────────────┘   └───────────────┘     └────────┬────────┘
                                                            │ subscribed by
                                                            ▼
                                                  8 background workers
                                                  (in lokilinux-api process)

                        ┌─────────────────────┐
   Go Agent  ──mTLS────▶│    lokilinux-grpc    │  FastAPI + grpcio, JSON-over-gRPC (50051)
  (fleet host)          └──────────┬───────────┘
                                   │ shares DB/cache/NATS with lokilinux-api
                                   ▼
                         same Postgres / Redis / NATS
```

Agents never receive inbound connections — they poll the control plane every 60 seconds via
an outbound gRPC heartbeat stream, and the control plane rides that same response channel to
push jobs, policy updates, reboot requests, and plugin actions back down.

## Service map (docker-compose.yml)

| Service | Image | Port(s) | Purpose |
|---|---|---|---|
| `postgres` | `timescale/timescaledb:2.28.1-pg17` | 5432 | Primary DB + `agent_metrics` TimescaleDB hypertable |
| `pgbouncer` | `edoburu/pgbouncer:v1.25.2-p0` | 6432→5432 | Connection pooling, `transaction` pool mode, 200 max clients / 20 default pool size |
| `nats` | `nats:2.10.29-alpine` | 4222 (client), 8222 (monitoring) | Event bus with JetStream (`--js`) |
| `redis` | `redis:7.4.9-alpine` | 6379 | Cache-aside store, AOF persistence, `allkeys-lru` eviction |
| `lokilinux-migrate` | built from `backend/Dockerfile` | — | One-shot `alembic upgrade head`, runs before `lokilinux-api` starts |
| `lokilinux-api` | built from `backend/Dockerfile` | 8000 (REST), 9090 (metrics) | FastAPI app: REST routers + all 8 NATS workers + lifespan-managed DB/cache/NATS clients |
| `lokilinux-grpc` | same image as `lokilinux-api` | 50051 | Standalone `python -m lokilinux.grpc_server`, mTLS-only agent endpoint |
| `lokilinux-frontend` | built from `frontend/Dockerfile` | 3000 | Nuxt 4 SSR app; hosts Better Auth server-side |

`lokilinux-api` and `lokilinux-grpc` are built from the identical backend image but run
different entrypoints/commands, and both connect independently to Postgres (via pgbouncer),
Redis, and NATS — they are two processes, not two replicas of one process.

## Authentication flow

Authentication is fully delegated to **Better Auth**, which runs inside the Nuxt 4 server
process (`frontend/server/utils/auth.ts`), backed by a Kysely + `pg` Postgres adapter pointed
at the same database as the rest of the platform. Enabled plugins: `username()`, `twoFactor()`
(TOTP, issuer name pulled from `branding.company_name` setting), `bearer()`, and `admin()`.
Sessions default to 7 days (`security.session_expiry_days`) with a 24-hour rolling refresh
window (`security.session_update_age_hours`), both overridable via the `settings` table (read
once at module load — changes require a frontend restart to take effect).

**Backend validation is opaque-token based, not JWT/JWKS.** FastAPI's
`lokilinux/auth/jwks_validator.py` (`get_current_user` dependency) takes the `Authorization:
Bearer <token>` header and calls `GET {BETTER_AUTH_URL}/api/auth/get-session` on the frontend
service, forwarding the same bearer token. There is no local signature verification and no
JWKS endpoint involved — Better Auth issues opaque session tokens, not RS256 JWTs.

> Note: `main.py`'s module docstring says auth is "validated via JWKS" — that comment is
> stale. The actual implementation (`jwks_validator.py`) validates via the Better Auth
> session endpoint, matching the behavior described here.

Request flow for every authenticated API call:

1. FastAPI reads the `Authorization` header; missing/malformed → `401`.
2. Check Redis for `ba:session:{token}` (60s TTL cache-aside). Cache hit returns immediately.
3. Check Redis negative cache `ba:down:{token}` (5s TTL) — if Better Auth was recently
   unreachable, fail fast with `503` instead of re-hitting a down service.
4. Otherwise call Better Auth's `/api/auth/get-session`, with a simple circuit breaker: one
   retry after a 1s delay on transient network errors or 5xx; any definitive response
   (2xx/4xx) is not retried.
5. `502`/`503` on unreachable/erroring auth service (and sets the negative cache); `401` on an
   invalid/expired session; `401` if the session has no `user`.
6. On success, the user's `role` is normalized to uppercase (so `require_role()` checks like
   `"ADMIN"` work regardless of how Better Auth cased it) and the user dict is cached in Redis
   for 60s under `ba:session:{token}`.

Roles: `ADMIN`, `MANAGER`, `OPERATOR`, `VIEWER`, `AUDITOR` (`role_assignments` table, `userrole`
Postgres enum). Role checks are enforced via a `require_role()` dependency
(`lokilinux/auth/dependencies.py`) layered on top of `get_current_user`.

Frontend-to-backend traffic is same-origin: the browser talks to Nuxt on `/api/v1/*`, which a
Nitro server proxy forwards to `lokilinux-api` (`API_INTERNAL_URL`), so the bearer token never
needs a cross-origin CORS exemption for normal UI usage. `lokilinux-api`'s own CORS middleware
still allows `settings.frontend_url` explicitly (methods restricted to
`GET/POST/PATCH/DELETE`) for any direct API access.

## Agent communication (gRPC + mTLS)

Agents are static Go binaries (`CGO_ENABLED=0`, `agent/cmd/agent/main.go`) that never accept
inbound connections. All communication is a single outbound bidirectional gRPC stream to
`lokilinux-grpc:50051`, secured with mutual TLS (agent presents a client cert issued from the
platform CA; the server requires and verifies it — `require_client_auth=True` in
`grpc_server.py`). Max message size is capped at 16 MB on both sides
(`grpc.max_recv_message_length` / `MaxCallRecvMsgSize`).

**Custom JSON codec, not binary protobuf.** Both the Go client
(`agent/internal/communication/grpc_client.go`) and the Python server
(`backend/lokilinux/grpc_server.py`) register a codec named `"proto"` that marshals/unmarshals
plain JSON instead of wire-format protobuf. The `.proto` file (`proto/lokilinux.proto`) still
defines the message shapes and is used to generate Go structs (`agent/gen/lokilinux/`), but
messages travel over the wire as JSON, deserialized server-side into a `SimpleNamespace` tree
(`grpc_server.py:_from_json`) and normalized into plain dicts by `AgentServicer._as_dict()`
before reaching `AgentService`. This is a deliberate interim design — the code comments mark
it as a stand-in for real protobuf serialization.

`proto/lokilinux.proto` declares two services:
- **`AgentService`** (agent is the gRPC client): `HeartbeatStream` (bidi stream — the only RPC
  actually wired up server-side), `ReportMetrics` (client-streaming), `SyncPolicy` (unary).
- **`PlatformService`** (internal, control-plane-to-control-plane): `ExecuteJobStream`,
  `InstallPlugin`. Declared in the proto but not implemented in `grpc_server.py`'s
  `_AgentServiceHandler`, which only wires `HeartbeatStream`.

### Heartbeat / job cycle

Every 60 seconds (`Heartbeat.IntervalSec` in `/etc/lokilinux/agent.yaml`), `agent.Manager.Run`
(`agent/internal/agent/manager.go`) drives one cycle:

1. Collect `SystemStatus` (hostname, OS/kernel/arch, disks, network interfaces, block devices,
   listening ports), the installed package list plus a SHA-256 checksum of the full list
   (delta-sync — server skips re-upserting packages if the checksum matches the last one it
   stored), and `AgentHealth` (CPU/memory/disk/swap %, connection failure count).
2. Drain any `pendingResults` from jobs executed since the last heartbeat.
3. Send `AgentHeartbeatRequest` over `HeartbeatStream`, `CloseSend()`, then block on `Recv()`
   for the single `AgentHeartbeatResponse`.
4. On success: reset `failCount` to 0, drop the reported results from the pending queue, and
   call `handleResponse` on anything the server sent back (`pending_jobs`, `policy` delta,
   `reboot`, `plugin_action`).
5. On failure: increment `failCount`; every 3rd consecutive failure forces `GRPCClient.Reconnect()`
   (tears down and redials the gRPC connection — grpc-go's built-in reconnect logic doesn't
   reliably recover a stream that's been failing with EOF, e.g. after a server restart).
   Backoff after 3+ consecutive failures doubles the interval each time, capped at 5 minutes.

Server-side (`backend/lokilinux/api/grpc/agent_service.py` → `AgentService.update_heartbeat`,
`backend/lokilinux/services/agent_service.py`):
- Looks the agent up by its identity string (`Agent.agent_id`), sets `status = ACTIVE` and
  `last_heartbeat = now()`.
- Overwrites hardware/system JSONB fields and scalar OS fields; upserts packages only if the
  checksum changed (`ON CONFLICT` upsert on `uq_packages_agent_name_version`); inserts one
  `AgentHealth` row per heartbeat (flags `is_disk_full` / `is_memory_critical` at ≥90%).
- Applies any `job_results` the agent is reporting back (agent has no other channel to report
  outcomes — it can only push results on its *next* heartbeat after execution) and recomputes
  the parent `Job.status` via `recompute_job_status`.
- Invalidates the agent's Redis cache entries, then returns up to 10 `PENDING` `JobResult`
  rows for that agent as the response's `pending_jobs` — gated so a job with
  `requires_approval=True` is withheld until `Job.approved_at` is set.

### Job dispatch on the agent (`handleResponse` in manager.go)

Each pending job in the heartbeat response is dispatched by `job_type`:

- `PLUGIN_INSTALL` → `modules.InstallPlugin` (downloads and verifies a plugin package).
- `ANSIBLE_PLAYBOOK` → `AnsibleExecutor.Execute` (see Ansible section below).
- anything else → `JobExecutor.Execute`, which runs `parameters.command` under `/bin/sh -c`
  with the job's `timeout_seconds` (or the agent's configured default), process-group-killed
  on timeout/cancellation, stdout/stderr each capped at 4 MB.

Results are queued in `pendingResults` and reported on the *next* heartbeat, not immediately —
there is no separate result-push RPC in use (`ReportMetrics`/`ExecuteJobStream` are declared in
the proto but not implemented).

### Local SQLite cache (offline operation)

Each agent keeps a local cache at `/var/lib/lokilinux/agent.db`
(`modernc.org/sqlite`, pure Go, no CGO), opened with a single connection
(`SetMaxOpenConns(1)`). Schema:

| Table | Purpose |
|---|---|
| `jobs` | Local job queue for offline/deferred execution — 30-day TTL (`expires_at`), purged daily by `Manager.runPurge` |
| `packages_cache` | Snapshot of the last-reported package list + checksum, per agent |
| `agent_config` | Generic key-value store |

This lets the agent continue operating (queueing jobs, tracking package state) if the control
plane is briefly unreachable, without re-sending a full package list every heartbeat once the
checksum matches.

## Event bus (NATS)

All topics are prefixed `lokilinux.` (`backend/lokilinux/nats_topics.py` is the single source
of truth — import the constants, never hardcode topic strings):

| Constant | Topic | Published by | Consumed by |
|---|---|---|---|
| `JOB_CREATED` | `lokilinux.job.created` | Job creation flow | — (jobs are actually delivered via the heartbeat response, not a live NATS push to agents) |
| `JOB_RESULT` | `lokilinux.job.result` | Agent-facing job completion path | `JobExecutorWorker` → `JobService.complete_job` |
| `POLICY_CHANGED` | `lokilinux.policy.changed` | Policy update flow | `PolicyWorker` |
| `POLICY_APPLY` | `lokilinux.policy.apply` | Policy service | `PolicyWorker` |
| `ALERT_CREATED` | `lokilinux.alert.created` | `AlertService.create_alert` | `NotificationWorker` (SMTP/Slack delivery), `AlertProcessorWorker` |
| `AGENT_UNHEALTHY` | `lokilinux.agent.unhealthy` | `HeartbeatMonitorWorker` (stale-heartbeat sweep) | `AlertProcessorWorker` |
| `CVE_DATABASE_UPDATED` | `lokilinux.cve.database.updated` | CVE feed ingestion | `CVEProcessorWorker` |
| `PLUGIN_INSTALL` | `lokilinux.plugin.install` | Plugin install flow | `PluginWorker` |
| `PLUGIN_UNINSTALL` | `lokilinux.plugin.uninstall` | Plugin uninstall flow | (plugin lifecycle handling) |

### The 8 NATS/background workers

All 8 are started in `lokilinux-api`'s FastAPI `lifespan` (`main.py`), share the same
`session_factory`/`RedisCache`/NATS connection as the REST app, and are stopped in reverse
order on shutdown.

1. **`JobExecutorWorker`** (`workers/job_executor.py`) — subscribes to `JOB_RESULT`; calls
   `JobService.complete_job(job_id, agent_id, exit_code, stdout, stderr, duration_ms)`.
2. **`CVEProcessorWorker`** (`workers/cve_processor.py`) — subscribes to
   `CVE_DATABASE_UPDATED`; reconciles the CVE feed against `agent_vulnerabilities`.
3. **`AlertProcessorWorker`** (`workers/alert_processor.py`) — subscribes to alert/health
   signals (`ALERT_CREATED`, `AGENT_UNHEALTHY`) and applies alert-rule/escalation logic.
4. **`PolicyWorker`** (`workers/policy_worker.py`) — subscribes to `POLICY_CHANGED` /
   `POLICY_APPLY`; propagates policy deltas that agents pick up on their next heartbeat.
5. **`PluginWorker`** (`workers/plugin_worker.py`) — subscribes to `PLUGIN_INSTALL`; invalidates
   `plugin:list:*` and `plugin:{id}:*` Redis cache patterns so the UI reflects an in-progress
   install. The actual install action reaches the agent through the heartbeat response.
6. **`HeartbeatMonitorWorker`** (`workers/heartbeat_monitor.py`) — **not** NATS-triggered; runs
   its own 60-second `asyncio` sweep loop (there's no event for "a heartbeat didn't arrive").
   Reads `fleet.heartbeat_timeout_minutes` from settings, marks any `ACTIVE` agent past that
   cutoff as `INACTIVE` via `AgentService.mark_inactive`, and publishes `AGENT_UNHEALTHY`.
7. **`RetentionCleanupWorker`** (`workers/retention_cleanup.py`) — periodic purge of aged data
   (e.g. old metrics/audit rows) per retention settings.
8. **`NotificationWorker`** (`workers/notification_worker.py`) — subscribes to `ALERT_CREATED`;
   reads `notifications.*` settings (SMTP host/from, Slack webhook URL) and delivers via SMTP
   (blocking `smtplib` call run in `asyncio.to_thread` so it doesn't stall the event loop) and/or
   a Slack incoming webhook. No-op if neither channel is configured; delivery failures are
   logged, never raised.

## Database

PostgreSQL 17 via the TimescaleDB 2.28.1 image, accessed exclusively through pgBouncer
(`transaction` pool mode) at `postgresql+psycopg://...@pgbouncer:5432/...`. All backend access
goes through SQLAlchemy async (`async_sessionmaker` + `AsyncSession`), engine built once at
startup with `pool_size=20`, `max_overflow=10`, `pool_recycle=3600`, `pool_pre_ping=True`
(`lokilinux/db.py`). Migrations are Alembic, applied by the one-shot `lokilinux-migrate`
container before `lokilinux-api` starts (13 revision files, `001` through `013`, as of this
writing).

### TimescaleDB hypertable

`agent_metrics` (time-series CPU/memory/disk/network/process counters per agent) is created as
a hypertable on `time` (`SELECT create_hypertable('agent_metrics', 'time', ...)`), with
composite primary key `(time, agent_id)`. Compression is enabled
(`timescaledb.compress_segmentby = 'agent_id'`) with a compression policy activating after 30
days (`add_compression_policy('agent_metrics', INTERVAL '30 days')`).

> Note: rollup aggregation policies (1min→5min→hourly) and a 365-day retention policy are
> referenced in project documentation/comments but are not present as `add_retention_policy`
> or continuous-aggregate calls in the migration files read for this document — treat any
> specific rollup/retention interval as unverified until an operator confirms it against the
> live database or a later migration adds it.
> <!-- VERIFY: agent_metrics retention (365 days) and 1min→5min→hourly rollup policy -->

### Core tables (by migration)

**`001_initial_schema`** — `policies`, `agents` (enum `agentstatus`:
`PENDING/REGISTERED/ACTIVE/INACTIVE/UNHEALTHY/MAINTENANCE`), `packages`, `cves` (with a
full-text GIN index over title+description), `package_vulnerabilities`, `jobs` (enum
`jobstatus`: `QUEUED/SCHEDULED/PENDING/RUNNING/COMPLETED/FAILED/TIMEOUT/CANCELLED`, plus a
partial unique index on `dedup_key` where non-null), `job_results`, `agent_vulnerabilities`,
`plugins` (enum `pluginstatus`:
`PENDING_INSTALL/INSTALLING/INSTALLED/INSTALLING_FAILED/ENABLED/DISABLED/ERROR`),
`plugin_installations`, `alert_rules` (self-referencing `escalation_policy` FK),
`alerts`, `audit_logs` (full-text GIN index), `policy_audit`, `user_profiles`,
`role_assignments` (enum `userrole`: `ADMIN/MANAGER/OPERATOR/VIEWER/AUDITOR`), `agent_health`,
`agent_metrics` (hypertable, see above), `settings`.

**`002_update_management`** — additional tables supporting patch/update tracking (four
`op.create_table` calls; consult the migration for exact columns).

**`007_categories_projects`** — `Category`, `Project` (agent grouping/tagging).

**`009_add_playbooks` → `012_add_ansible_projects`** — the Ansible automation schema (see
below).

**`013_add_agent_health_totals`** — extends `agent_health` with additional total/aggregate
columns.

There is **no `repositories` table** despite the proto defining a `Repository` message — the
`repo.default_mirror_url` setting is a placeholder for a future repo-mirror feature, not a
currently-implemented one.

### ORM models (`backend/lokilinux/models/`)

`Agent`, `AgentHealth`, `AgentMetrics`, `AgentStatus`, `Alert`, `AlertRule`, `AuditLog`,
`RoleAssignment`, `Setting`, `UserProfile`, `UserRole`, `Category`, `Project`,
`AgentVulnerability`, `CVE`, `Package`, `PackageVulnerability`, `Job`, `JobResult`, `JobStatus`,
`Plugin`, `PluginInstallation`, `PluginStatus`, `Policy`, `PolicyAudit` — plus
`ansible_project.py`, `ansible_role.py`, `playbook.py`, `playbook_template.py` for the Ansible
plugin's own tables.

## Backend module layout

```
backend/lokilinux/
├── main.py               FastAPI app, lifespan (DB/cache/NATS/workers), middleware, /health, /ready
├── grpc_server.py         Standalone gRPC entrypoint (python -m lokilinux.grpc_server), mTLS, JSON codec
├── db.py                  build_engine() / build_session_factory() — shared by API, gRPC server, and workers
├── dependencies.py        FastAPI Depends(get_db) / Depends(get_cache) / Depends(get_nats), pulled from app.state
├── cache.py               RedisCache — cache-aside helpers, standardized TTL constants, pattern invalidation
├── nats_topics.py         Central constants for every NATS topic string
├── config.py              Settings (pydantic) loaded from environment
├── settings_schema.py     Typed accessors for the DB-backed `settings` table (get_setting_value, get_all_settings)
├── auth/
│   ├── jwks_validator.py  get_current_user — opaque Better Auth session validation (see Auth flow)
│   └── dependencies.py    require_role(), safe_user_uuid()
├── api/
│   ├── v1/routers/        14 REST routers (see below)
│   └── grpc/
│       └── agent_service.py   AgentServicer.HeartbeatStream — bridges the gRPC layer into AgentService
├── models/                SQLAlchemy ORM models, one module per domain
├── schemas/                Pydantic request/response schemas
├── services/               Business logic (AgentService, JobService, PlaybookService, etc.)
├── middleware/
│   └── rate_limit.py      Redis-backed fixed 60s-window rate limiter, DB-configured, fail-open
└── workers/                8 background workers (see Event bus section)
```

### API v1 routers (`api/v1/__init__.py`, mounted at `/api/v1`)

`dashboard`, `categories`, `servers`, `jobs`, `vulnerabilities` (cves router), `policies`,
`plugins`, `playbooks`, `playbook-templates`, `ansible-roles`, `ansible-projects`, `alerts`,
`admin`, `agent` + `agents` (agent install/registration, two prefixes from the same
`agent_install.py` module). 14 routers total.

## Agent state machine

```
PENDING → REGISTERED → ACTIVE ⇄ INACTIVE
                          ↕
                      UNHEALTHY
                          ↕
                     MAINTENANCE
```

Backed by the Postgres enum `agentstatus`
(`PENDING, REGISTERED, ACTIVE, INACTIVE, UNHEALTHY, MAINTENANCE`). New agents default to
`PENDING`. Every accepted heartbeat sets status to `ACTIVE`
(`AgentService.update_heartbeat`). `HeartbeatMonitorWorker`'s 60-second sweep demotes any
`ACTIVE` agent whose `last_heartbeat` is older than `fleet.heartbeat_timeout_minutes` to
`INACTIVE` and publishes `lokilinux.agent.unhealthy`.

## Job state machine

```
QUEUED → SCHEDULED → PENDING → RUNNING → COMPLETED
                                   ├──────→ FAILED
                                   ├──────→ TIMEOUT
                                   └──────→ CANCELLED
```

Backed by the Postgres enum `jobstatus`. A `Job` targets one or more agents
(`target_servers` JSONB); per-agent outcomes are tracked in individual `job_results` rows
(free-text `status`, not the same enum). `recompute_job_status` rolls per-agent `job_results`
back up into the parent `Job.status`. Jobs may require approval
(`requires_approval` + `approved_at`) — an agent will not receive an approval-gated job in its
heartbeat response until `approved_at` is set, regardless of `approved_by` (which can be
legitimately `NULL` because Better Auth's nanoid user IDs frequently don't parse as UUIDs).
A `dedup_key` with a partial unique index prevents duplicate in-flight jobs of the same
type/target/parameters.

The gRPC-level `JobResult.State` enum from the proto
(`PENDING/RUNNING/COMPLETED/FAILED/TIMEOUT/CANCELLED/ROLLED_BACK`) is mapped down to the
`job_results.status` string on ingest (`ROLLED_BACK` currently collapses to `FAILED` — there is
no dedicated status value for it yet).

## Plugin system

Plugins are tracked in the `plugins` table (`Plugin` model) with lifecycle states
(`PENDING_INSTALL → INSTALLING → INSTALLED → ENABLED/DISABLED`, or `INSTALLING_FAILED`/`ERROR`
on failure), a JSONB `manifest` (name, version, description, author, entrypoint, required
permissions), and per-agent install tracking in `plugin_installations`. The control plane keeps
installed plugin binaries under `/opt/lokilinux/plugins` (`PLUGIN_DIR`, mounted as the
`plugins_dir` Docker volume). Install/uninstall requests flow through NATS
(`lokilinux.plugin.install` / `lokilinux.plugin.uninstall`) to invalidate cached plugin views,
but the actual install action is delivered to the agent as a `PLUGIN_INSTALL`-type job in the
heartbeat response, executed by `modules.InstallPlugin` on the agent (downloads and verifies
the plugin package, checksum-checked per `PluginInstallRequest.checksum_sha256` in the proto).

Routers `plugins`, `playbooks`, `playbook-templates`, `ansible-roles`, `ansible-projects` all
gate certain operations on a `Plugin.is_enabled` check — e.g. every Ansible playbook route
403s immediately if the `ansible-automation` plugin row is disabled.

## Ansible automation integration

Ansible is implemented as a built-in plugin (seeded by migration `009_add_playbooks` as the
`ansible-automation` `Plugin` row, `plugin_type = "control-plane"`, disabled by default) rather
than an external service — there is no AWX/Tower dependency and no SSH involved.

**Storage model** mirrors the existing `Policy.rules` JSONB pattern instead of introducing a
file-storage layer:
- `playbooks` — playbook YAML stored directly as `content` (`TEXT`), versioned (`version` int),
  optional `default_extra_vars` JSONB, optional `role_ids` (JSONB array), optional
  `project_id` FK to `ansible_projects`.
- `ansible_roles` — each role's files stored as a JSONB map of relative-path → file content
  (`files` column), analogous to a real `roles/<name>/` directory tree flattened into one row.
- `playbook_templates` — AWX "Job Template" equivalent: a saved
  (playbook + default agent list + default extra_vars) combination for one-click re-launch,
  referencing `playbooks.id` rather than duplicating content.
- `ansible_projects` — groups playbooks (equivalent of a real Ansible `projects/<name>/` tree);
  `project_id` is nullable, and ungrouped playbooks surface as "Debug/Uncategorized" in the UI.

**Execution model** — local, not SSH. When a playbook is launched
(`POST /api/v1/playbooks/{id}/execute`), the backend creates a `Job` with
`job_type = "ANSIBLE_PLAYBOOK"` whose `parameters` snapshot the playbook content, extra_vars,
and any referenced roles. On the target agent, `manager.go`'s job dispatch routes this to
`AnsibleExecutor.Execute` (`agent/internal/modules/ansible_executor.go`), which:

1. Fails fast with a clear error if `ansible-playbook` isn't on the target's `PATH`.
2. Writes the playbook to a fresh `os.MkdirTemp` directory as `playbook.yml`, extra_vars as
   `extravars.json`, and any roles under `<dir>/roles/<role-name>/<relative-path>` — with role
   name/path validated against traversal (`..`, absolute paths, `/` in role names all rejected)
   as defense-in-depth against a compromised control plane, even though the backend is also
   expected to validate on write.
3. Runs `ansible-playbook -i localhost, -c local -e @extravars.json playbook.yml` via `argv`
   (never through a shell string), so untrusted playbook/extra_vars content can't break out of
   a command line the way `JobExecutor`'s raw shell commands could.
4. Captures stdout/stderr (4 MB cap each), enforces the job's timeout by killing the whole
   process group on cancellation, and returns a `JobResult` reported on the next heartbeat like
   any other job.

Playbook and role authoring/management is exposed under `/api/v1/playbooks`,
`/api/v1/playbook-templates`, `/api/v1/ansible-roles`, and `/api/v1/ansible-projects`, all
requiring the `ansible-automation` plugin to be enabled.

## Key abstractions

- **`RedisCache`** (`cache.py`) — cache-aside wrapper with domain helpers
  (`invalidate_agent`, `invalidate_cve_database`) and standardized TTLs: agent status 30s, job
  status 60s, CVE data 3600s.
- **`get_current_user` / `require_role`** (`auth/`) — the sole auth boundary for every REST
  route; see Authentication flow above.
- **`AgentService`** (`services/agent_service.py`) — owns heartbeat ingestion, package sync,
  health recording, job-result application, and the agent inactivity transition.
- **`JobService`** (`services/job_service.py`) — job creation (with dedup-key computation),
  approval, and completion/status-recompute logic shared by the REST API and
  `JobExecutorWorker`.
- **`AgentServicer`** (`api/grpc/agent_service.py`) — the only implemented gRPC handler;
  bridges the JSON-codec gRPC stream into `AgentService`.
- **`nats_topics` constants** — single source of truth preventing topic-string typos across
  17+ publish/subscribe call sites.

## Directory structure rationale

```
lokilinux/
├── backend/     FastAPI 0.138.x control plane (Python 3.11) — REST API, gRPC server, NATS workers, Alembic migrations
├── agent/       Go 1.24 static binary (CGO_ENABLED=0) — runs on every managed Linux host
├── frontend/    Nuxt 4 + Vue 3 + TypeScript — web UI, hosts Better Auth server-side
├── proto/       Single lokilinux.proto — message/service definitions (server codec sends JSON, not wire protobuf)
├── certs/       Pre-generated mTLS certs (CA, server cert, agent cert template) for local/dev bring-up
├── scripts/     init-certificates.sh, docker-init.sh, install-agent.sh
├── kubernetes/  Empty — planned, not implemented
└── docs/        Architecture and operational documentation
```

The backend/agent/frontend split follows the trust boundary: the agent is untrusted compute
running on fleet hosts (Go, statically linked, minimal footprint, mTLS-authenticated), the
backend is the trusted control plane (Python, full DB/cache/bus access), and the frontend is a
separate trusted-but-browser-facing tier that owns its own auth database access (Better Auth)
rather than proxying credentials through the backend.
