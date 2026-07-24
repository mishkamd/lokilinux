<!-- generated-by: gsd-doc-writer -->
# Deployment

LokiLinux ships as a Docker Compose stack (8 containers) plus a fleet of Go agents installed on
managed servers. There is no Kubernetes manifest yet — the `kubernetes/` directory exists in the
repo but is currently empty; it is a placeholder for future work, not a supported deployment path.

## Deployment Targets

| Target | Config file | Status |
|---|---|---|
| Docker Compose (production) | `docker-compose.yml` | Supported |
| Docker Compose (development, hot-reload) | `docker-compose.yml` + `docker-compose.dev.yml` | Supported |
| Kubernetes | `kubernetes/` | Planned, not implemented — directory is empty |
| Managed agent fleet | `scripts/install-agent.sh` + `.deb`/`.rpm` packages | Supported |

No CI/CD workflow files were found in the repository (no `.github/workflows/`). Builds and deploys
described below are run manually via `make` / `docker compose`.

## Production Stack (Docker Compose)

`docker-compose.yml` defines 8 services on a single bridge network (`lokilinux-network`):

| Service | Image | Ports | Purpose |
|---|---|---|---|
| `postgres` | `timescale/timescaledb:2.28.1-pg17` | 5432 (internal) | Primary DB + TimescaleDB hypertables |
| `pgbouncer` | `edoburu/pgbouncer:v1.25.2-p0` | 6432→5432 | Connection pooling (transaction mode) |
| `nats` | `nats:2.10.29-alpine` (+JetStream) | 4222, 8222 | Event bus |
| `redis` | `redis:7.4.9-alpine` | 6379 | Cache (AOF persistence, allkeys-lru) |
| `lokilinux-migrate` | built from `backend/Dockerfile` | — | One-shot: `alembic upgrade head`, then exits |
| `lokilinux-api` | built from `backend/Dockerfile` | 8000, 9090 | REST API + Prometheus metrics |
| `lokilinux-grpc` | built from `backend/Dockerfile` | 50051 | Standalone gRPC server (mTLS) |
| `lokilinux-frontend` | built from `frontend/Dockerfile` | 3000 | Nuxt 4 web UI + Better Auth |

Startup ordering is enforced with `depends_on` conditions: `pgbouncer` waits on `postgres`
healthy; `lokilinux-migrate` waits on `pgbouncer` healthy; `lokilinux-api` and `lokilinux-grpc`
wait on `pgbouncer`, `nats`, and `redis` healthy; `lokilinux-api` additionally waits for
`lokilinux-migrate` to complete successfully before starting; `lokilinux-frontend` waits on
`lokilinux-api` healthy.

### Bringing up the stack

```bash
make up      # docker compose up -d
make down    # docker compose down
make build   # docker compose build
make logs    # docker compose logs -f
make ps      # docker compose ps
```

`make up` and `make build` invoke `docker compose` directly against `docker-compose.yml` only —
they assume `.env`, certificates, and Docker volumes already exist. For a from-scratch first run,
use `make init` (see below) instead.

### Development stack

```bash
make dev     # docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

`docker-compose.dev.yml` overrides the production compose file: it builds from `Dockerfile.dev`
for backend and frontend, mounts source directories as bind volumes for hot-reload
(`uvicorn --reload` for the API, `npm run dev` for the frontend), exposes `postgres` (5432),
`pgbouncer` (6432), `nats` (4222/8222/6222 including the cluster port), and `redis` (6379) on the
host, and raises container memory limits to 4G for build/dev tooling headroom.

## First-Run Initialization

`make init` runs `scripts/docker-init.sh`, which performs the full bootstrap in one pass:

1. Requires `.env` to exist — if missing, copies `.env.example` to `.env` and exits, prompting you
   to edit it and re-run.
2. Generates certificates into `.certs/` (via `scripts/init-certificates.sh`) if `.certs/ca.crt`
   does not already exist.
3. Creates runtime directories: `logs/api`, `logs/frontend`, `backups`.
4. Creates the named Docker volumes: `lokilinux-postgres-data`, `lokilinux-nats-data`,
   `lokilinux-redis-data`, `lokilinux-plugins`, `lokilinux-certs`.
5. Copies the generated certificates from `.certs/` into the `lokilinux-certs` volume using a
   throwaway `alpine` container, fixing permissions (`600` on keys, `644` on certs).
6. Runs `docker compose build`.
7. Starts infrastructure services first (`postgres`, `nats`, `redis`), then `pgbouncer` after a
   5-second delay.
8. Polls `pg_isready` inside the `postgres` container (up to 30 attempts, 3s apart) before
   proceeding.
9. Starts `lokilinux-api`, `lokilinux-grpc`, `lokilinux-frontend`.
10. Polls `GET /health` inside the `lokilinux-api` container (up to 20 attempts, 3s apart).
11. Runs `alembic upgrade head` inside `lokilinux-api`, then runs the Better Auth migration
    (`npx tsx scripts/migrate-db.ts` inside `frontend/`) to create the `user`/`session`/`account`
    tables.
12. Bootstraps the default admin user: since Better Auth's admin API requires an existing admin
    session, the script signs up the first admin through the public `/api/auth/sign-up/email`
    endpoint (reading `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`, generating a random password
    if unset), then promotes that user to `role='admin'` directly via `psql` (chicken-and-egg
    bootstrap — this is the only place a role is set with raw SQL instead of the app).
13. Prints final `docker compose ps` status, access URLs, and the generated admin credentials.

```bash
make init    # bash scripts/docker-init.sh
```

Re-running `make init` is not idempotent for the admin bootstrap step in general, but the sign-up
call tolerates "already exists" (422 / "already exists" response body) and logs it rather than
failing.

### Rebuilding from scratch

`scripts/rebuild.sh` is a heavier reset useful during development iteration: it stops the stack,
clears Nuxt build artifacts (`frontend/.nuxt`, `frontend/.output`), prunes the Docker builder
cache and dangling images/containers, optionally wipes all `lokilinux-*` volumes with `--clean`,
rebuilds images, regenerates certificates directly into the `lokilinux-certs` volume (inline
`openssl` calls in a throwaway `alpine` container — duplicates the cert logic in
`init-certificates.sh` rather than calling it), brings the stack up, and curls `/` on the frontend
and `/health` on the API to confirm both are reachable.

```bash
bash scripts/rebuild.sh          # rebuild, keep data
bash scripts/rebuild.sh --clean  # rebuild, also wipe all named volumes
```

## Certificate Generation

mTLS between the gRPC server and every agent is backed by a self-signed CA generated by
`scripts/init-certificates.sh`:

```bash
make certs
# equivalent to:
bash scripts/init-certificates.sh [certs-dir] [hostname] [validity-days]
# defaults: certs-dir=/etc/lokilinux/certs, hostname=lokilinux.example.com, validity-days=365
```

What it generates, all under the target certs directory:

- `ca.key` / `ca.crt` — 4096-bit self-signed CA (subject `/CN=LokiLinux-CA/O=LokiLinux/C=US`),
  distributed to every agent as the trust anchor.
- `server.key` / `server.crt` — the gRPC server certificate, signed by the CA. SAN list is built
  automatically from the hostname argument (classified as `DNS:` or `IP:` depending on whether it
  parses as an IPv4 literal) plus `DNS:lokilinux-grpc`, `DNS:localhost`, `IP:127.0.0.1`. Extra SANs
  can be added via `EXTRA_SANS="host1,host2"` (comma-separated) in the environment.
- `agent-template.key` / `agent-template.crt` — a client certificate template signed by the CA,
  used as the basis for per-agent certs issued during enrollment.

The script is **idempotent by default**: if `ca.crt` already exists in the target directory it
exits immediately without touching anything, because regenerating the CA would break trust for
every already-enrolled agent. Pass `FORCE=1` to deliberately regenerate.

Private keys are written `600`; certificates and CSRs are `644`.

In the Docker Compose flow, certs land in `.certs/` on the host first, then get copied into the
`lokilinux-certs` named volume (mounted read-only at `/etc/lokilinux/certs` in `lokilinux-api` and
`lokilinux-grpc`, and read-write in dev for the same path).

## Database Migrations on Deploy

Migrations run automatically as part of every `docker compose up`/`make up` via the
`lokilinux-migrate` one-shot service:

- Built from the same `backend/Dockerfile` image as the API.
- `restart: "no"` — it runs `alembic upgrade head` once and exits; it is not a long-running
  container.
- Depends on `pgbouncer` being healthy before starting.
- `lokilinux-api` declares `depends_on: lokilinux-migrate: condition: service_completed_successfully`,
  so the API container will not start until migrations have applied cleanly.
- Connects through pgBouncer (`postgresql+psycopg://...@pgbouncer:5432/...`), not directly to
  Postgres.

Manual migration commands (e.g., against a running stack, or to generate a new revision):

```bash
cd backend
alembic upgrade head                       # apply pending migrations
alembic revision --autogenerate -m "..."   # generate a new migration from model changes
```

Note that `scripts/docker-init.sh` additionally runs a second, separate migration step after the
Alembic one: the Better Auth schema migration (`npx tsx scripts/migrate-db.ts` in `frontend/`),
which creates the `user`/`session`/`account`/`verification` tables used by authentication. This
step is not part of the `lokilinux-migrate` container and only runs during `make init`.

## Environment Setup

Copy `.env.example` to `.env` and fill in every required value before deploying (see
[docs/CONFIGURATION.md](CONFIGURATION.md) for the full variable reference). At minimum for a
production deploy, set real values for:

- `POSTGRES_PASSWORD`, `REDIS_PASSWORD` — generate with `openssl rand -base64 48`
- `BETTER_AUTH_SECRET` — generate with `openssl rand -base64 48`
- `PLATFORM_HOSTNAME` — the public hostname agents and the SAN list on the server cert will use
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — used once by `make init` to bootstrap the first admin

<!-- VERIFY: production secret values (POSTGRES_PASSWORD, REDIS_PASSWORD, BETTER_AUTH_SECRET, admin credentials) must be provisioned per-deployment; no secret manager integration was found in the repository, so these are expected to live only in the target host's .env file. -->

## Agent Fleet Rollout

### Building agent binaries and packages

```bash
make agent-build          # static linux/amd64 binary, CGO_ENABLED=0 → agent/bin/lokilinux-agent
make agent-build-arm64    # static linux/arm64 binary → agent/bin/lokilinux-agent-arm64
make agent-package        # both arches + .tar.gz, and .deb/.rpm if nfpm is installed
make agent-test           # go test ./... -v -race -cover
```

`agent-package` depends on `agent-build` and `agent-build-arm64`, then:

1. Copies `scripts/loki-cli.sh` into `agent/bin/loki` and marks it executable.
2. Creates `lokilinux-agent_<version>_linux_amd64.tar.gz` and the `arm64` equivalent, each
   bundling the platform binary plus `loki`.
3. If `nfpm` is installed (`go install github.com/goreleaser/nfpm/v2/cmd/nfpm@latest`), packages
   `.deb` and `.rpm` for both `amd64` and `arm64` via `nfpm package --packager deb|rpm`. If `nfpm`
   is not found, this step is skipped with a warning — `.tar.gz` archives are still produced.

`VERSION` defaults to `git describe --tags --abbrev=0`, falling back to `0.1.0` if no tags exist.

<!-- VERIFY: nfpm package config (nfpm.yaml) referenced by `nfpm package --packager deb|rpm` was not found in this exploration pass — confirm its location under agent/ before relying on .deb/.rpm output. -->

The API container mounts `./agent/bin` read-only at `/opt/lokilinux/packages`, and serves agent
binaries to installing hosts via the `AGENT_DOWNLOAD_BASE` / agent download endpoint referenced in
`scripts/install-agent.sh`.

### Installing an agent on a managed server

`scripts/install-agent.sh` is designed to be curl-installed:

```bash
curl -fsSL https://<platform-url>/install | bash -s -- --token=<enrollment-token>
# or, run locally against a checked-out copy:
bash scripts/install-agent.sh --token=<enrollment-token> [--url=<platform-url>] [--name=<agent-name>]
```

<!-- VERIFY: the `/install` HTTP path shown in the curl one-liner is a convention comment in the script header, not a route confirmed present in the backend API routers during this exploration pass. -->

What it does on the target host:

1. Detects OS (`/etc/os-release`) and architecture (`uname -m`, normalized to `amd64`/`arm64`).
2. Downloads the agent binary from `$PLATFORM_URL/api/v1/agent/download`, authenticated with the
   enrollment token as a bearer token and `X-OS`/`X-Arch` headers.
3. Registers the host with the control plane via `POST $PLATFORM_URL/api/v1/agents/register`,
   sending hostname, OS distro/version, arch, and kernel version. The response provides
   `agent_id`, `agent_cert`, optionally `agent_key`, and the `ca_cert`.
4. Creates `/etc/lokilinux/certs` (mode 750), `/var/lib/lokilinux` (755), `/var/log/lokilinux`
   (755), `/opt/lokilinux/plugins` (755).
5. Writes the issued agent certificate, key (if returned), and CA cert into
   `/etc/lokilinux/certs/`.
6. Writes `/etc/lokilinux/agent.yaml` (mode 640) with the gRPC endpoint (host derived from
   `$PLATFORM_URL`, port 50051), cert paths, agent ID/hostname, a 60s heartbeat interval with a
   30s timeout, the local SQLite cache path, and the plugin directory.
7. Installs the binary to `/usr/local/bin/lokilinux-agent`.
8. Writes and enables a systemd unit, `/etc/systemd/system/lokilinux-agent.service`, running as
   `root` with `Restart=always`, `RestartSec=10s`, and sandboxing (`ProtectSystem=strict`,
   `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true`, with `ReadWritePaths` scoped to
   `/var/lib/lokilinux` and `/var/log/lokilinux`).
9. Starts the service and verifies it is active; on failure it dumps the last 30 journal lines and
   exits non-zero.

For fleet rollout at scale, this script can be distributed via configuration management (Ansible,
etc. — see the Ansible automation feature documented separately) or a golden-image/cloud-init step
that runs it with a per-host or per-batch enrollment token.

<!-- VERIFY: no bulk/fleet-rollout orchestration script for install-agent.sh (e.g., Ansible playbook driving mass enrollment) was found in this exploration pass — confirm whether one exists elsewhere in the repo (e.g., under an ansible/ or automation/ directory) before documenting a specific bulk-rollout command. -->

## Rollback Procedure

No automated rollback tooling (CI pipeline, platform-specific rollback command) was found in the
repository. The general approach with this stack:

1. **Application containers** (`lokilinux-api`, `lokilinux-grpc`, `lokilinux-frontend`): re-tag and
   redeploy the previous image version. Images are tagged `lokilinux/api:${LOKILINUX_VERSION}` and
   `lokilinux/frontend:${LOKILINUX_VERSION}` — set `LOKILINUX_VERSION` in `.env` back to the last
   known-good value and run `docker compose up -d` to redeploy just those services.
2. **Database migrations**: Alembic supports downgrading a specific number of revisions
   (`alembic downgrade -1` from `backend/`), but this is a manual, destructive operation not
   wired into any script — review the target migration before running it, and take a Postgres
   backup first (`BACKUP_DIR` / `pg_dump` — no automated backup script was found in the repo).
3. **Certificates**: the CA is deliberately not regenerated in place (see idempotency note above)
   because it would invalidate every enrolled agent's trust chain — a cert rollback effectively
   means restoring the previous `lokilinux-certs` volume contents from backup, not re-running
   `init-certificates.sh`.
4. **Agents**: the systemd unit's `Restart=always` means a bad agent binary rollout requires
   re-running `install-agent.sh` (or manually replacing `/usr/local/bin/lokilinux-agent`) with the
   previous binary version and restarting the service.

<!-- VERIFY: no dedicated backup/restore script for the postgres_data volume was found; BACKUP_DIR and BACKUP_RETENTION_DAYS are defined in .env.example but no script in scripts/ implements the backup itself. -->

## Monitoring

No monitoring/observability library (Sentry, Datadog, New Relic, OpenTelemetry) was found in
`backend/Dockerfile`'s pinned dependency list or elsewhere in the repository.

What exists natively:

- `lokilinux-api` exposes Prometheus-format metrics on port `9090`.
- Container healthchecks are defined for every service in `docker-compose.yml`
  (`pg_isready` for Postgres/pgBouncer, `wget --spider` against NATS's `/healthz` and the
  frontend's `/health`, `redis-cli ping`, a `curl -f` against the API's `/health`, and a raw TCP
  connect check for the gRPC port). `docker compose ps` / `make ps` surfaces health status.
- The agent writes structured logs to `/var/log/lokilinux/agent.log` and to the systemd journal
  (`journalctl -u lokilinux-agent -f`).

<!-- VERIFY: no Prometheus/Grafana scrape config or dashboard was found in the repository — confirm whether metrics scraping and alerting are set up outside this repo before pointing contributors at a specific dashboard URL. -->
