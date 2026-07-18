# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LokiLinux — enterprise Linux fleet management platform. Centralized patch management, vulnerability scanning, compliance automation, and remediation for 10K–100K+ Linux servers.

## Repository Structure

```
lokilinux/
├── backend/          # FastAPI 0.138.1 (Python 3.11)
├── agent/            # Go 1.24.0 static binary (CGO_ENABLED=0)
├── frontend/         # Nuxt 4.4.8 + Vue 3.5 + TypeScript
├── proto/            # Single protobuf file (lokilinux.proto)
├── certs/            # Pre-generated mTLS certs (CA, server, agent template)
├── scripts/          # init-certificates.sh, docker-init.sh, install-agent.sh
├── kubernetes/       # Empty (planned, not implemented)
└── docs/             # Architecture specs (some outdated)
```

## Commands

### Stack
```bash
make up          # docker compose up -d (production)
make down        # docker compose down
make build       # docker compose build
make dev         # dev stack (hot-reload, bind mounts, no resource limits)
make logs        # docker compose logs -f
make ps          # docker compose ps
make init        # first-run: certs + volumes + migrations + admin user
```

### Backend (FastAPI)
```bash
cd backend
pip install -e ".[dev]"
uvicorn lokilinux.main:app --reload                    # dev server on :8000
alembic upgrade head                                    # run DB migrations
alembic revision --autogenerate -m "..."                # generate migration
pytest tests/ -v --cov=lokilinux                        # all tests
pytest tests/unit/ -v --cov=lokilinux                   # unit tests
pytest tests/integration/ -v                            # integration tests
black . && ruff check . && mypy lokilinux/              # lint + type check
```

### Agent (Go)
```bash
make agent-build                    # linux/amd64 static binary
make agent-build-arm64              # linux/arm64 static binary
make agent-package                  # builds both arches + .tar.gz/.deb/.rpm
make agent-test                     # go test ./... -v -race -cover
```

### Frontend (Nuxt 4)
```bash
cd frontend
npm install
npm run dev         # dev server on :3000 (HMR)
npm run build       # production build
npm run test        # vitest run
npm run test:coverage
```

### Protobuf
```bash
make proto          # regenerates agent/gen/ + backend/lokilinux/gen/ from proto/lokilinux.proto
```

### Certificates
```bash
make certs          # runs scripts/init-certificates.sh
```

## Architecture

### Service Map (8 containers in docker-compose.yml)

| Service | Tech | Port | Purpose |
|---------|------|------|---------|
| postgres | TimescaleDB 2.28.1-pg17 (PostgreSQL 17) | 5432 | Primary DB + time-series |
| pgbouncer | edoburu/pgbouncer 1.25.2 | 6432→5432 | Connection pooling (transaction mode) |
| nats | NATS 2.10.29-alpine + JetStream | 4222/8222 | Event bus |
| redis | Redis 7.4.9-alpine | 6379 | Cache (AOF, allkeys-lru) |
| lokilinux-migrate | FastAPI image (one-shot) | — | alembic upgrade head on deploy |
| lokilinux-api | FastAPI + grpcio | 8000/9090 | REST API + Prometheus metrics |
| lokilinux-grpc | Same FastAPI image | 50051 | Standalone gRPC server (mTLS) |
| lokilinux-frontend | Nuxt 4 (Node 22) | 3000 | Web UI + Better Auth |

### Auth Flow
- **Better Auth** runs inside Nuxt 4 server (`frontend/server/utils/auth.ts`) with Kysely + PostgreSQL adapter
- Frontend uses username/password + TOTP plugins; sessions are 7 days with 24h rolling refresh
- FastAPI validates opaque tokens by calling `GET {better_auth_url}/api/auth/get-session` (not JWKS — `backend/lokilinux/auth/jwks_validator.py`)
- Session result cached in Redis for 60s. Roles: ADMIN, MANAGER, OPERATOR, VIEWER, AUDITOR

### Agent Communication
- Agent binary (Go, static) connects outbound via gRPC + mTLS to port 50051
- Custom JSON gRPC codec overrides protobuf serialization on both sides
- Every 60s heartbeat carries: system info, packages (with SHA256 checksums), vulnerabilities, metrics
- Response contains pending jobs + policy delta
- Agent stores local SQLite cache at `/var/lib/lokilinux/agent.db` (30-day retention)
- Agent config: `/etc/lokilinux/agent.yaml`; plugins: `/opt/lokilinux/plugins/`

### Event Bus (NATS)
- All topics prefixed with `lokilinux.`
- `lokilinux.job.created` — picked up by agents via heartbeat response
- `lokilinux.job.result` — consumed by `JobExecutorWorker`
- `lokilinux.cve.database.updated` — consumed by `CVEProcessorWorker`
- `lokilinux.policy.changed` — policy delta pushed to agents
- `lokilinux.agent.unhealthy` — published by `HeartbeatMonitorWorker` on stale heartbeat, consumed by `AlertProcessorWorker`
- `lokilinux.alert.created` — consumed by `NotificationWorker` (SMTP/Slack delivery)

### Database
- TimescaleDB hypertable: `agent_metrics` (compression at 30 days, retention 365 days, rollup 1min→5min→hourly)
- Core tables: agents, agent_health, jobs, job_results, cves, packages, package_vulnerabilities, agent_vulnerabilities, policies, policy_audit, alert_rules, alerts, audit_logs, user_profiles, role_assignments, settings, plugins, plugin_installations
  (no `repositories` table yet — `repo.default_mirror_url` setting is a placeholder for a future repo-mirror feature)
- All backend DB access via SQLAlchemy async (`async_sessionmaker` + `AsyncSession`)

### Key Backend Patterns
- `lokilinux/db.py` — `build_engine()` + `build_session_factory()`, shared by FastAPI, gRPC server, and NATS workers
- `lokilinux/dependencies.py` — FastAPI `Depends(get_db)`, `Depends(get_cache)`, `Depends(get_nats)`
- `lokilinux/cache.py` — `RedisCache` class with cache-aside pattern, TTL constants
- `lokilinux/api/v1/__init__.py` — mounts 9 routers under `/api/v1/`
- gRPC server (`grpc_server.py`) uses `GenericRpcHandler` + manual JSON serialization, not generated gRPC stubs
- `lokilinux/nats_topics.py` — central constants for all NATS topic strings; import instead of writing raw strings
- 8 NATS workers wired into `main.py` lifespan: JobExecutor, CVEProcessor, AlertProcessor, Policy, Plugin, HeartbeatMonitor, RetentionCleanup, Notification

### Agent State Machine
`PENDING → REGISTERED → ACTIVE` (with `INACTIVE`, `UNHEALTHY`, `MAINTENANCE` transitions)

### Job State Machine
`QUEUED → SCHEDULED → PENDING → RUNNING → COMPLETED` (or `FAILED`, `TIMEOUT`, `CANCELLED`)

## Code Standards
- **Python:** black (line-length=100), ruff (E/F/I/N/W), mypy (strict), pytest
- **Go:** gofmt, golangci-lint, go test -race
- **TypeScript/Vue:** ESLint + prettier, vitest
- Command format: tabs in Makefile

## Key Environment Variables (.env)
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_PASSWORD`, `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `PLATFORM_HOSTNAME`, `AGENT_VERSION`, `LOG_LEVEL`, `ENVIRONMENT`, `DATABASE_URL`, `NATS_URL`, `REDIS_URL`
