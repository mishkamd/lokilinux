<!-- generated-by: gsd-doc-writer -->
# Configuration

LokiLinux is configured primarily through a single `.env` file consumed by `docker-compose.yml`
(and `docker-compose.dev.yml` for local development), plus a per-host `agent.yaml` for each
managed server's agent. A third layer — live, admin-editable platform settings stored in the
`settings` table — covers values that can change without a redeploy (see
[Platform Settings (database-backed)](#platform-settings-database-backed) below).

## Environment Variables

Copy `.env.example` to `.env` before running `docker compose up` (or `make init`, which does this
for you). Generate secrets with `openssl rand -base64 48`.

| Variable | Required | Default | Description |
|----------|----------|---------|--------------|
| `ENVIRONMENT` | Optional | `production` | `production` or `development`. Read by the backend (`lokilinux/config.py`); `debug` is derived as `environment == "development"`. |
| `PLATFORM_NAME` | Optional | `LokiLinux` | Display name, currently informational in `.env.example`. |
| `PLATFORM_HOSTNAME` | Optional | `lokilinux.example.com` | Documented hostname for the deployment; not read directly by backend `Settings` (superseded by `PUBLIC_URL`, see below). |
| `LOKILINUX_VERSION` | Optional | `latest` | Docker image tag used for `lokilinux/api` and `lokilinux/frontend` in `docker-compose.yml`. |
| `POSTGRES_HOST` | Optional | `postgres` | Documented in `.env.example`; the compose file hardcodes the `postgres` service name internally. |
| `POSTGRES_PORT` | Optional | `5432` | Same as above. |
| `POSTGRES_DB` | Required | `lokilinux` | Primary database name, used to build `DATABASE_URL` in `docker-compose.yml`. |
| `POSTGRES_USER` | Required | `lokilinux` | Database user. |
| `POSTGRES_PASSWORD` | **Required** | — | Database password. No default — compose passes it through unquoted; must be set. |
| `TIMESCALE_HOST` / `TIMESCALE_PORT` | Optional | `postgres` / `5432` | Documented for the metrics database, which lives in the same Postgres/TimescaleDB container. |
| `TIMESCALE_DB` | Optional | `lokilinux_metrics` | Metrics database name. |
| `TIMESCALE_USER` / `TIMESCALE_PASSWORD` | Optional | — | Metrics DB credentials (documented in `.env.example`; not referenced by `docker-compose.yml`, which uses the primary Postgres credentials for all services). |
| `PGBOUNCER_HOST` / `PGBOUNCER_PORT` | Optional | `pgbouncer` / `6432` | pgBouncer connection pooler, sits in front of Postgres. All backend services connect through `pgbouncer:5432` internally. |
| `REDIS_URL` | Optional | `redis://redis:6379` | Base Redis URL (backend actually builds an authenticated URL: `redis://:${REDIS_PASSWORD}@redis:6379/0`, see `docker-compose.yml`). |
| `REDIS_PASSWORD` | **Required** | — | Redis auth password, passed to `redis-server --requirepass`. |
| `REDIS_MAXMEMORY` | Optional | `2gb` | Redis `maxmemory`, eviction policy is `allkeys-lru`. |
| `NATS_URL` | Optional | `nats://nats:4222` | NATS JetStream event bus URL. |
| `BETTER_AUTH_SECRET` | **Required** | — | Shared secret used by Better Auth (Nuxt) and by the backend to validate sessions. Generate with `openssl rand -base64 48`. |
| `BETTER_AUTH_URL` | Required | `http://localhost:3000` | Base URL of the Better Auth instance (the Nuxt frontend). The backend calls `GET {BETTER_AUTH_URL}/api/auth/get-session` to validate bearer tokens (`backend/lokilinux/auth/jwks_validator.py`); it is not a JWKS/JWT flow despite the file name. |
| `GRPC_PORT` | Optional | `50051` | Port for the standalone mTLS gRPC server (agent communication). |
| `AGENT_CERT_DIR` | Optional | `/etc/lokilinux/certs` | Mount path for mTLS certs inside API/gRPC containers. |
| `CA_CERT_PATH` / `CA_KEY_PATH` | Optional | `/etc/lokilinux/certs/ca.crt` / `ca.key` | CA certificate/key paths used to sign new agent certs. |
| `SERVER_CERT_PATH` / `SERVER_KEY_PATH` | Optional | `/etc/lokilinux/certs/server.crt` / `server.key` | gRPC server's own mTLS cert/key. |
| `CERT_VALIDITY_DAYS` | Optional | `365` | Documented in `.env.example` for `scripts/init-certificates.sh`. |
| `CERT_RENEWAL_DAYS` | Optional | `30` | Same as above. |
| `PLUGIN_DIR` | Optional | `/opt/lokilinux/plugins` | Shared volume mount where agent-side plugins are dropped on managed hosts and where the control-plane stores plugin artifacts. |
| `PLUGINS_ENABLED` / `PLUGINS_SANDBOX_MODE` / `PLUGINS_MAX_MEMORY_MB` / `PLUGINS_MAX_CPU_CORES` | Optional | `true` / `true` / `256` / `1` | Documented in `.env.example`; plugin sandboxing knobs. |
| `AGENT_HEARTBEAT_INTERVAL` | Optional | `60` (seconds) | Documented in `.env.example`. The actual per-agent heartbeat cadence is set in each host's `agent.yaml` (`heartbeat.interval_seconds`), written by `scripts/install-agent.sh`. |
| `AGENT_HEARTBEAT_TIMEOUT` | Optional | `30` | Same caveat as above. |
| `AGENT_MAX_OFFLINE_DAYS` | Optional | `30` | Documented in `.env.example`. |
| `AGENT_REGISTRATION_TOKEN_TTL` | Optional | `3600` | Documented in `.env.example`. |
| `AGENT_VERSION` | Optional | `0.1.0` | Version string embedded in generated agent install scripts/packages (`Settings.agent_version`). |
| `AGENT_DOWNLOAD_BASE` | Optional | empty | Overrides the base URL agents are told to download packages from. Falls back to `PUBLIC_URL`/`PLATFORM_URL` when unset. |
| `FRONTEND_URL` | Optional | `http://localhost:3000` | Used by the backend as the CORS origin (`Settings.frontend_url`). |
| `PUBLIC_URL` | Optional | `http://localhost:3000` | Single public entry point for the whole platform — `docker-compose.yml` derives both `PLATFORM_URL` and `FRONTEND_URL` (backend) and `BETTER_AUTH_URL` (frontend) from it. Not listed in `.env.example` but read directly by `docker-compose.yml`. |
| `CVE_FEED_UPDATE_INTERVAL` | Optional | `86400` | Documented in `.env.example`; CVE sync interval in seconds. <!-- VERIFY: CVE feed sync worker is a stub per settings_schema.py comments — confirm before relying on this value in production --> |
| `CVE_FEED_SOURCES` | Optional | `ubuntu,debian,rhel,nvd` | Comma-separated CVE feed source list. |
| `NVD_API_KEY` | Optional | empty | NIST NVD API key for CVE feed lookups. |
| `LOG_LEVEL` | Optional | `info` | Passed to backend (`Settings.log_level`) and agent (`agent.yaml` `logging.level`). |
| `LOG_FORMAT` | Optional | `json` | Documented in `.env.example`. |
| `DEBUG` | Optional | `false` | Also settable per-service in `docker-compose.dev.yml` (`DEBUG: "true"` for API/gRPC dev containers). |
| `SMTP_ENABLED` / `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_ADDRESS` | Optional | `false` / — / `587` / — / — / `noreply@lokilinux.example.com` | Outbound email for `NotificationWorker`. Overlaps with the DB-backed `notifications.*` settings group — see below. |
| `SLACK_ENABLED` / `SLACK_WEBHOOK_URL` | Optional | `false` / empty | Slack delivery for `NotificationWorker`. Also mirrored under DB-backed `notifications.slack_webhook_url`. |
| `BACKUP_DIR` | Optional | `/var/backups/lokilinux` | Documented in `.env.example`. <!-- VERIFY: no backup worker/script referencing this var was found in the explored source; confirm it is still consumed --> |
| `BACKUP_RETENTION_DAYS` | Optional | `30` | Same as above. |
| `S3_BACKUP_ENABLED` / `S3_BUCKET` / `S3_REGION` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_ENDPOINT` | Optional | `false` / `lokilinux-backups` / `eu-central-1` / — / — / `https://s3.amazonaws.com` | Documented in `.env.example`. <!-- VERIFY: S3 backup integration not found wired into backend/agent source during exploration --> |
| `ADMIN_EMAIL` | Optional | `admin@lokilinux.local` | Used only by `scripts/docker-init.sh` to bootstrap the first admin user. |
| `ADMIN_PASSWORD` | Optional | random (`openssl rand -base64 16`, printed at the end of `make init`) | Same as above — set it ahead of time for a known password. |

`docker-compose.yml` additionally computes `DATABASE_URL` internally as:
```
postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@pgbouncer:5432/${POSTGRES_DB}
```
This is not a standalone `.env` variable — it is assembled from `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` for the `lokilinux-migrate`, `lokilinux-api`, and `lokilinux-grpc` services, always pointed at `pgbouncer`, never at `postgres` directly.

## Backend Settings (`lokilinux/config.py`)

The FastAPI backend loads a `pydantic-settings` `Settings` object from `.env` (case-insensitive,
unknown keys ignored). Fields without a listed default are **required** — startup fails with a
validation error if they are absent:

| Field | Env var | Required | Default |
|-------|---------|----------|---------|
| `database_url` | `DATABASE_URL` | **Required** | — |
| `redis_url` | `REDIS_URL` | Optional | `redis://localhost:6379` |
| `nats_url` | `NATS_URL` | Optional | `nats://localhost:4222` |
| `grpc_port` | `GRPC_PORT` | Optional | `50051` |
| `better_auth_url` | `BETTER_AUTH_URL` | **Required** | — |
| `better_auth_secret` | `BETTER_AUTH_SECRET` | **Required** | — |
| `agent_cert_dir` | `AGENT_CERT_DIR` | Optional | `/etc/lokilinux/certs` |
| `log_level` | `LOG_LEVEL` | Optional | `INFO` |
| `environment` | `ENVIRONMENT` | Optional | `development` |
| `frontend_url` | `FRONTEND_URL` | Optional | `http://localhost:3000` |
| `platform_url` | `PLATFORM_URL` | Optional | `http://localhost:8000` |
| `agent_download_base` | `AGENT_DOWNLOAD_BASE` | Optional | `""` |
| `agent_version` | `AGENT_VERSION` | Optional | `0.1.0` |
| `agent_package_dir` | `AGENT_PACKAGE_DIR` | Optional | `/opt/lokilinux/packages` |
| `better_auth_admin_token` | `BETTER_AUTH_ADMIN_TOKEN` | Optional | `""` |

`Settings.debug` is a computed property (`environment == "development"`), not a separate env var
on the backend side.

## Agent Configuration (`/etc/lokilinux/agent.yaml`)

Each managed host runs the Go agent with a YAML config at `/etc/lokilinux/agent.yaml`, generated
by `scripts/install-agent.sh` during `curl | bash` install and loaded by `agent/internal/config/config.go`.

Defaults applied by `Load()` when a field is omitted (`applyDefaults` in `config.go`):

| Field | Default |
|-------|---------|
| `heartbeat.interval_sec` | `60` |
| `heartbeat.timeout_sec` | `30` |
| `heartbeat.retry_backoff_max` | `600` |
| `cache.sqlite_db` | `/var/lib/lokilinux/agent.db` |
| `cache.retention_days` | `30` |
| `job_execution.max_parallel_jobs` | `2` |
| `job_execution.timeout_seconds` | `3600` |
| `logging.level` | `info` |

The Go struct's expected top-level keys are `platform`, `identity`, `heartbeat`, `cache`,
`job_execution`, `logging` (with `platform.url`, `platform.grpc_endpoint`, and
`identity.{agent_id,cert_path,key_path,ca_path}` nested underneath).

<!-- VERIFY: scripts/install-agent.sh currently writes agent.yaml with a different top-level shape
(platform_url, grpc:, agent:, plugins: as siblings) than the Go Config struct expects
(platform:, identity:, no top-level plugins/agent block) — confirm which is authoritative
before relying on install-agent.sh output as a config reference. -->

No `agent.yaml.example` template ships in the repository; the file is generated entirely by the
install script at install time using values from the agent registration flow (agent ID, mTLS
certs, and `PLATFORM_URL`).

## Frontend Configuration

The Nuxt 4 frontend (`frontend/nuxt.config.ts`) reads these environment variables at build/runtime:

| Variable | Default | Purpose |
|----------|---------|---------|
| `API_INTERNAL_URL` | `http://lokilinux-api:8000` | Server-side (SSR) and Nitro proxy target for `/api/v1/**` — routes browser requests to the FastAPI container without CORS. |
| `NUXT_PUBLIC_API_BASE` | `/api/v1` | Client-side relative API base (same-origin, proxied by Nitro). Baked in as a Docker build arg in `docker-compose.yml`. |
| `BETTER_AUTH_SECRET` | — | Shared with the backend; used by Better Auth's Kysely/Postgres adapter. |
| `BETTER_AUTH_URL` | — | Set to `${PUBLIC_URL}` in `docker-compose.yml`. |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | — | Better Auth connects directly to Postgres (via `pgbouncer` in compose) for its own session/user tables. |

## Platform Settings (database-backed)

Beyond `.env`, LokiLinux stores a second layer of runtime-editable settings in the `settings`
table (`lokilinux/settings_schema.py`, `SETTINGS_SCHEMA`), managed from the admin UI
(`frontend/pages/admin/settings.vue`) via `GET/PUT /api/v1/admin/settings`-style endpoints. These
values are stored as flat `"{group}.{key}"` rows and take effect without a restart:

| Group | Keys | Notes |
|-------|------|-------|
| `agent` | `platform_url`, `version`, `download_base` | Mirrors `.env` agent distribution settings but overridable live. |
| `security` | `ldap_enabled`, `ldap_host`, `ldap_port`, `ldap_bind_dn`, `ldap_bind_password`, `ldap_search_base`, `ldap_use_ssl`, `require_2fa`, `session_expiry_days`, `session_update_age_hours`, `password_min_length`, `rate_limit_enabled`, `rate_limit_per_minute`, `audit_log_retention_days` | LDAP fields are storage-only — no bind logic is implemented (per source comment). |
| `notifications` | `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `slack_webhook_url` | Overlaps with `SMTP_*`/`SLACK_*` env vars; DB values are the ones actually read by `NotificationWorker` at send time. |
| `fleet` | `heartbeat_timeout_minutes` (default `5`) | Used by `HeartbeatMonitorWorker` to flag agents unhealthy. |
| `retention` | `metrics_days` (default `365`) | Storage-only — does not alter the TimescaleDB compression/retention policy, which requires an `ALTER` on the continuous aggregate (per source comment). |
| `cve` | `feed_source_url`, `sync_interval_hours` (default `24`) | Storage-only — CVE sync is currently a stub. |
| `branding` | `company_name` (default `LokiLinux`), `logo_url` (default `/logo.svg`) | Publicly readable (`PUBLIC_GROUPS`), used on the login page before authentication. |
| `plugins` | `marketplace_url` | Storage-only — nothing consumes it yet. |
| `repo` | `default_mirror_url` | Storage-only — placeholder for a future repo-mirror feature; no `repositories` table exists yet. |

Secret-typed keys (`security.ldap_bind_password`, `notifications.smtp_password`) are masked as
`••••••••` on read and never overwritten if the mask is echoed back unchanged on update.

## Per-Environment Overrides

- **Production:** `docker compose up -d` (equivalently `make up`) uses `docker-compose.yml` only —
  no extra ports exposed beyond what's declared, resource limits enforced via `deploy.resources`.
- **Development:** `make dev` runs `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`.
  The dev override exposes Postgres (`5432`), NATS cluster port (`6222`), and Redis (`6379`) on the
  host, sets `ENVIRONMENT=development` / `DEBUG=true` on the API and gRPC containers, mounts source
  directories as bind mounts for hot reload, and raises container memory limits (2G/512M → 4G) to
  give `uvicorn --reload` and Vite headroom.
- Backend, frontend, and root each keep a separate `.env` (`backend/.env`, `frontend/.env`, `.env`
  at the repo root) — all three are gitignored. The root `.env` drives `docker-compose.yml`; the
  per-service files are used when running `uvicorn` or `npm run dev` outside Docker.
- `ENVIRONMENT`/`NODE_ENV`-style branching in code is limited to the computed `Settings.debug`
  property on the backend; no separate `.env.production` / `.env.development` files exist in the
  repository.

<!-- VERIFY: PLATFORM_HOSTNAME (.env.example) and the actual public hostname/URL used in a given
deployment are infrastructure-specific and not verifiable from the repository alone. -->
