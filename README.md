<!-- generated-by: gsd-doc-writer -->
# LokiLinux

Enterprise Linux fleet management platform — centralized patch management, vulnerability scanning, compliance automation, and remediation for 10K–100K+ Linux servers.

## Architecture

```
                  ┌──────────────────────────────────────┐
                  │         Frontend (Nuxt 4)            │
                  │         http://localhost:3000         │
                  └──────────────┬───────────────────────┘
                                 │ REST
                  ┌──────────────▼───────────────────────┐
                  │       Control Plane (FastAPI)         │
                  │    REST :8000  │  gRPC :50051 (mTLS) │
                  └──────┬────────┴──────────┬───────────┘
                         │                   │
          ┌──────────────┼───────────────────┼───────────┐
          │              ▼                   ▼           │
          │  ┌──────────────┐  ┌──────────────────────┐  │
          │  │ PostgreSQL   │  │    Linux Agents (Go) │  │
          │  │ + TimescaleDB│  │    Static binary     │  │
          │  │ + pgBouncer  │  │    Outbound-only     │  │
          │  └──────────────┘  │    60s heartbeat     │  │
          │  ┌──────┐ ┌──────┐ └──────────────────────┘  │
          │  │ Redis│ │ NATS │                            │
          │  └──────┘ └──────┘                            │
          └───────────────────────────────────────────────┘
```

**Three layers:**

| Layer | Tech | Role |
|-------|------|------|
| **Control Plane** | FastAPI 0.138.1 (Python 3.11) | REST API, gRPC server, job orchestration, CVE processing, Ansible automation |
| **Linux Agent** | Go (static binary, CGO_ENABLED=0) | Heartbeat, package inventory, vulnerability scan, job + playbook execution |
| **Frontend** | Nuxt 4.4.8 + Vue 3 + TypeScript | Dashboard, fleet management, Ansible automation UI, plugin marketplace, user admin |

**Data flow:** Agent dials out via mTLS gRPC → heartbeat every 60s carries system info + packages + vulnerabilities → receives pending jobs + policy delta in response → Frontend polls REST for updates.

## Infrastructure Components

| Service | Technology | Port | Purpose |
|---------|-----------|------|---------|
| `lokilinux-frontend` | Nuxt 4 (Node 22) | 3000 | Web UI + Better Auth |
| `lokilinux-api` | FastAPI + uvicorn + grpcio | 8000, 9090 | REST API + Prometheus metrics |
| `lokilinux-grpc` | grpcio + mTLS | 50051 | Agent communication |
| `postgres` | TimescaleDB 2.28.1 (PG17) | 5432 | Primary DB + time-series |
| `pgbouncer` | pgBouncer (transaction mode) | 6432 | Connection pooling |
| `redis` | Redis 7.4.9 | 6379 | Cache (AOF, allkeys-lru) |
| `nats` | NATS 2.10.29 + JetStream | 4222, 8222 | Event bus |
| `lokilinux-migrate` | Alembic | — | One-shot DB migrations |

## Quick Start

### Prerequisites
- Docker 24+
- Docker Compose v2
- `make`

### First run

```bash
# 1. Create and edit environment file
cp .env.example .env
# Edit .env — set passwords, hostname, secrets

# 2. Full initialization (certs → build → start → migrate → admin user)
make init

# Or step by step:
make certs    # Generate CA + mTLS certificates
make build    # Build all Docker images
make up       # Start the stack
```

After `make init` completes, the admin credentials are printed to the terminal.

For local development with hot-reload, use `make dev` instead of `make up` (uses `docker-compose.dev.yml` to expose Postgres/pgBouncer/NATS ports locally).

### Access points

| URL | Description |
|-----|-------------|
| `http://localhost:3000` | Web UI |
| `http://localhost:8000/docs` | API docs (Swagger) |
| `http://localhost:8000/health` | API health check |
| `nats://localhost:4222` | NATS (JetStream enabled) |

## First-Time Authentication

The default admin user is created automatically by `make init`.

- **Login page:** `http://localhost:3000/auth/login`
- **Email:** `admin@lokilinux.local`
- **Password:** randomly generated during init (printed at the end)

To set a known password beforehand, add to `.env`:

```bash
ADMIN_EMAIL=admin@lokilinux.local
ADMIN_PASSWORD=your-secure-password
```

Auth is handled by **Better Auth** (embedded in the Nuxt frontend). The backend validates Bearer tokens against Better Auth's session endpoint. Roles: `ADMIN`, `MANAGER`, `OPERATOR`, `VIEWER`, `AUDITOR`.

## Ansible Automation

An AWX-like automation layer runs alongside patch management, built on 4 entities:

| Entity | Purpose |
|--------|---------|
| **Projects** (`ansible_projects`) | Group playbooks; `default_agent_ids` acts as the project's inventory (the live fleet is the inventory — no static hosts files) |
| **Roles** (`ansible_roles`) | Reusable file sets stored as a JSONB path→content map, materialized under `<tmpdir>/roles/<name>/` at execution time |
| **Playbooks** (`playbooks`) | Raw YAML, versioned on every edit, optionally scoped to a project and linked to `role_ids` |
| **Job Templates** (`playbook_templates`) | Saved (playbook + default agents + default extra_vars) combo — the AWX "Job Template" equivalent, launchable repeatedly |

Execution runs locally on each target agent (`ansible-playbook --connection=local`) as a normal `Job`, gated behind the `ansible-automation` plugin being enabled. Full details: [docs/ANSIBLE_AUTOMATION.md](docs/ANSIBLE_AUTOMATION.md).

## Plugin System

`plugins.py` + the `plugins` table track a marketplace-style install lifecycle: `PENDING_INSTALL → INSTALLING → INSTALLED → ENABLED` (or `INSTALLING_FAILED` / `DISABLED` / `ERROR`). Plugin types: control-plane, agent, ui, notification. Agent-side plugins are dropped into `/opt/lokilinux/plugins/` on the managed host. UI lives at `/plugins`.

## Makefile Targets

### Stack

```bash
make up       # Start production stack (detached)
make down     # Stop all containers
make build    # Build all Docker images
make dev      # Start with hot-reload (dev mode)
make logs     # Tail all service logs
make ps       # Show container status
make init     # First-run initialization
```

### Agent

```bash
make agent-build         # Build static binary (linux/amd64)
make agent-build-arm64   # Build static binary (linux/arm64)
make agent-package       # .tar.gz + .deb + .rpm for both arches
make agent-test          # Run agent tests with race detector
```

### Other

```bash
make proto    # Regenerate Go + Python from proto/*.proto
make certs    # Generate CA + server certificates
```

## Docker Compose Structure

`docker-compose.yml` defines 8 services on a shared `lokilinux-network`. All long-running services have health checks. `lokilinux-migrate` runs `alembic upgrade head` once and exits.

Service dependencies: `postgres` → `pgbouncer` → `lokilinux-migrate` → `lokilinux-api` / `lokilinux-grpc` → `lokilinux-frontend`

`docker-compose.dev.yml` is a dev override (used by `make dev`) that exposes Postgres, pgBouncer, and NATS ports locally and enables verbose Postgres query logging.

## Directory Structure

```
lokilinux/
├── backend/              # FastAPI application
│   ├── lokilinux/
│   │   ├── api/v1/       # 15 REST routers (servers, jobs, cves, policies, playbooks, ansible-projects, ansible-roles, playbook-templates, plugins, alerts, admin, agent-install, dashboard, categories)
│   │   ├── api/grpc/     # gRPC service handlers
│   │   ├── auth/         # JWT validation, role dependencies
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic API schemas
│   │   ├── services/     # Business logic
│   │   └── workers/      # NATS async consumers
│   ├── alembic/          # Alembic migrations
│   └── Dockerfile
├── agent/                # Go agent
│   ├── cmd/agent/        # Entry point
│   ├── internal/
│   │   ├── agent/        # Manager loop
│   │   ├── communication/# gRPC client (mTLS)
│   │   ├── modules/      # system_info, packages, vuln, metrics, jobs, ansible_executor, plugin_installer
│   │   └── storage/      # SQLite cache
│   └── .nfpm.yaml        # Package config (.deb/.rpm)
├── frontend/             # Nuxt 4 application
│   ├── pages/            # File-based routing (servers, jobs, alerts, policies, vulnerabilities, plugins, automation/ansible/{projects,roles,playbooks,templates}, admin/*)
│   ├── stores/           # Pinia stores
│   ├── composables/      # useAuth, useServers, useJobs, etc.
│   ├── server/           # Better Auth API handler + middleware
│   └── Dockerfile
├── proto/                # Protobuf definitions
│   └── lokilinux.proto
├── scripts/              # docker-init.sh, init-certificates.sh, install-agent.sh, loki-cli.sh, rebuild.sh
├── docs/                 # Architecture specifications + plugin-sdk (Go, Python)
├── docker-compose.yml
├── docker-compose.dev.yml
└── Makefile
```

## Essential Environment Variables

| Variable | Purpose |
|----------|---------|
| `POSTGRES_USER` | Database user (default: `lokilinux`) |
| `POSTGRES_PASSWORD` | Database password |
| `POSTGRES_DB` | Database name (default: `lokilinux`) |
| `REDIS_PASSWORD` | Redis password |
| `BETTER_AUTH_SECRET` | Better Auth signing secret |
| `ADMIN_EMAIL` | Default admin email |
| `ADMIN_PASSWORD` | Default admin password |
| `PLATFORM_HOSTNAME` | Server hostname (for certs) |
| `AGENT_VERSION` | Agent binary version (default: `0.23.2`) |
| `LOG_LEVEL` | Logging level (default: `info`) |
| `DATABASE_URL` | Async SQLAlchemy connection string |
| `NATS_URL` | NATS event bus connection string |
| `REDIS_URL` | Redis connection string |
| `ENVIRONMENT` | `development` \| `production` |
