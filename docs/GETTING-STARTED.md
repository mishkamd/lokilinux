<!-- generated-by: gsd-doc-writer -->
# Getting Started

This guide walks through a first-time LokiLinux setup: prerequisites, initializing the
Docker Compose stack, logging in as admin, and enrolling your first agent.

## Prerequisites

- **Docker** 24+ and **Docker Compose v2** (`docker compose`, not the legacy `docker-compose`)
- **GNU Make**
- **OpenSSL** (used by `scripts/init-certificates.sh` to generate the mTLS CA and server cert)
- Ports `3000`, `8000`, `9090`, `50051`, `4222`, `8222`, `5432`/`6432`, `6379` free on the host
  (production compose publishes all of these; see `docker-compose.yml`)

Backend and frontend containers are built from source by `make build` / `make init` — you do
not need Python 3.11, Node 22, or Go installed locally unless you plan to run those services
outside Docker.

## Installation Steps

### 1. Clone the repository

```bash
git clone <repository-url> lokilinux
cd lokilinux
```

### 2. Create your environment file

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `POSTGRES_PASSWORD`, `REDIS_PASSWORD` — strong passwords
- `BETTER_AUTH_SECRET` — generate with `openssl rand -base64 48`
- `PLATFORM_HOSTNAME` — the hostname agents and browsers will use to reach the platform
  (used as the CN/SAN on the generated TLS certificate)
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — optional; if left unset, `make init` creates
  `admin@lokilinux.local` with a random password and prints it at the end

See [CONFIGURATION.md](./CONFIGURATION.md) for the full variable reference.

### 3. Run first-time initialization

```bash
make init
```

`make init` runs `scripts/docker-init.sh`, which performs the full bootstrap in order:

1. Verifies `.env` exists (creates it from `.env.example` and exits if missing — re-run after editing)
2. Generates the mTLS CA, server certificate, and agent certificate template into `.certs/`
   via `scripts/init-certificates.sh` (skipped if certs already exist, unless `FORCE=1`)
3. Creates `logs/api`, `logs/frontend`, and `backups` directories
4. Creates the named Docker volumes (`lokilinux-postgres-data`, `lokilinux-nats-data`,
   `lokilinux-redis-data`, `lokilinux-plugins`, `lokilinux-certs`)
5. Copies the generated certificates into the `lokilinux-certs` volume
6. Builds all Docker images (`docker compose build`)
7. Starts infrastructure services first: `postgres`, `nats`, `redis`, then `pgbouncer`
8. Waits for PostgreSQL to report ready
9. Starts `lokilinux-api`, `lokilinux-grpc`, `lokilinux-frontend`
10. Waits for the API `/health` endpoint to respond
11. Runs backend migrations (`alembic upgrade head`) and frontend/Better Auth migrations
    (`npx tsx scripts/migrate-db.ts`, which creates the `user`/`session`/`account` tables)
12. Creates the default admin user via Better Auth's sign-up endpoint, then promotes it to
    `role='admin'` directly in Postgres (bootstrap workaround, since the admin-only
    `/admin/create-user` API needs an existing admin session)
13. Prints final container status and the admin login credentials

This is a single command — you do not need to run `make certs`, `make build`, or `make up`
separately. Those targets exist for manual/step-by-step control if you prefer:

```bash
make certs    # scripts/init-certificates.sh — CA + server + agent-template certs only
make build    # docker compose build — build images only
make up       # docker compose up -d — start containers only (no migrations, no admin bootstrap)
```

If you use the manual path, you still need to run migrations and create an admin user
yourself; `make init` is the supported way to get a working stack from zero.

## First Run

After `make init` completes, it prints something like:

```
Access:
  Web UI : https://<PLATFORM_HOSTNAME>
  API    : http://localhost:8000/docs
  gRPC   : localhost:50051 (mTLS)

Admin credentials:
  Email   : admin@lokilinux.local
  Password: <randomly generated or your ADMIN_PASSWORD>
```

Verify the stack is healthy:

```bash
make ps      # all 8 services should show "healthy" or "Up"
make logs    # tail logs if something looks wrong
```

Open the web UI locally at `http://localhost:3000/auth/login` and sign in with the printed
admin credentials. The API's interactive OpenAPI docs are at `http://localhost:8000/docs`.

### Enrolling your first agent

Agents connect outbound over mTLS gRPC and never require an inbound port on the managed host.

1. In the web UI (or via API), create an enrollment token:
   ```bash
   curl -X POST http://localhost:8000/api/v1/agent/enrollment-token \
     -H "Authorization: Bearer <your-session-token>" \
     -H "Content-Type: application/json" \
     -d '{"label": "my-first-server"}'
   ```
   This returns a 24-hour token (`_ENROLLMENT_TTL = 86400` hardcoded in
   `backend/lokilinux/api/v1/routers/agent_install.py`; the `AGENT_REGISTRATION_TOKEN_TTL` env var in
   `.env.example` is currently unused by this code path) and a ready-to-run `install_command`.
2. On the target Linux server, run the returned command — it downloads and runs
   `scripts/install-agent.sh` via the platform's `/api/v1/agent/install.sh` endpoint:
   ```bash
   curl -fsSL <platform-url>/api/v1/agent/install.sh | bash -s -- --token=<token> --url=<platform-url>
   ```
3. The script detects OS/arch from `/etc/os-release` and `uname -m`, downloads the matching
   agent binary, registers with `/api/v1/agents/register`, installs its mTLS certificate and
   CA under `/etc/lokilinux/certs/`, and starts reporting.
4. Confirm enrollment: the new agent should appear in the **Servers** page in the web UI within
   one heartbeat interval (60s by default).

For manual builds instead of the download endpoint, use `make agent-build` (linux/amd64) or
`make agent-build-arm64`, or `make agent-package` to produce `.tar.gz`/`.deb`/`.rpm` artifacts.

## Common Setup Issues

- **`.env not found` and `docker-init.sh` exits immediately** — expected on the very first run.
  It copies `.env.example` to `.env` for you and exits so you can edit values before continuing;
  re-run `make init` after editing.
- **Certificates already exist warning is skipped, but hostname changed** — `init-certificates.sh`
  is idempotent by design (regenerating the CA breaks trust for already-enrolled agents). If you
  changed `PLATFORM_HOSTNAME` before any agents were enrolled, force regeneration:
  `FORCE=1 bash scripts/init-certificates.sh .certs <new-hostname>`, then re-copy certs into the
  `lokilinux-certs` volume and restart `lokilinux-grpc`.
- **API or frontend health check never turns healthy** — check `make logs`; the most common
  cause is a missing/weak `BETTER_AUTH_SECRET` or `POSTGRES_PASSWORD` left as the placeholder
  value from `.env.example`.
- **Port already in use** — `docker-init.sh` publishes 3000, 8000, 9090, 50051, 4222, 8222, and
  Postgres/Redis ports on the host; stop any conflicting local services first, or adjust the
  `ports:` mappings in `docker-compose.yml`.
- **Agent install fails with a 401/403** — enrollment tokens expire after 24 hours (hardcoded
  `_ENROLLMENT_TTL = 86400` in `agent_install.py`; `AGENT_REGISTRATION_TOKEN_TTL` is not consulted);
  generate a new token if the install command was not run promptly.

## Next Steps

- [CONFIGURATION.md](./CONFIGURATION.md) — full environment variable reference and per-service settings
- [ARCHITECTURE.md](./ARCHITECTURE.md) — system components, data flow, and key abstractions
- `../README.md` — project overview, service map, and directory structure
