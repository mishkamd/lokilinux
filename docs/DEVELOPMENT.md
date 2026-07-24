<!-- generated-by: gsd-doc-writer -->
# Development Guide

LokiLinux has three independently developed services: a FastAPI backend, a Go agent, and a Nuxt 4 frontend. Each has its own dependency install, dev server, and lint/test commands. Use `make dev` to run the full stack with hot-reload if you want everything wired together; use the per-service commands below when iterating on one component in isolation.

## Local Setup

Copy the environment file and generate certificates once before starting any service:

```bash
cp .env.example .env
make certs
```

Then either run the full dev stack (Postgres, pgBouncer, NATS, Redis, and all three services with hot-reload and local ports exposed):

```bash
make dev
```

...or install and run each service natively (faster iteration, needs local Postgres/NATS/Redis or the `make dev` infra containers running).

### Backend (FastAPI)

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn lokilinux.main:app --reload
```

Runs on `:8000`. Requires `DATABASE_URL`, `REDIS_URL`, `NATS_URL`, and `BETTER_AUTH_URL` in the environment (see `docs/CONFIGURATION.md`).

### Agent (Go)

```bash
cd agent
go build -o bin/lokilinux-agent ./cmd/agent
```

Static binary, no runtime dependencies. Requires an `/etc/lokilinux/agent.yaml` config pointing at the gRPC endpoint (`:50051`, mTLS).

### Frontend (Nuxt 4)

```bash
cd frontend
npm install
npm run dev
```

Runs on `:3000` (Nuxt dev server with HMR, bound to `0.0.0.0`).

## Build Commands

### Backend (`backend/`)

| Command | Description |
|---------|-------------|
| `pip install -e ".[dev]"` | Install package in editable mode with dev dependencies (pytest, black, ruff, mypy, testcontainers) |
| `uvicorn lokilinux.main:app --reload` | Run dev server with auto-reload on `:8000` |
| `alembic upgrade head` | Apply all pending DB migrations |
| `alembic revision --autogenerate -m "..."` | Generate a new migration from model changes |
| `pytest tests/ -v --cov=lokilinux` | Run full test suite with coverage |
| `pytest tests/unit/ -v --cov=lokilinux` | Run unit tests only |
| `pytest tests/integration/ -v` | Run integration tests only (spins up a real TimescaleDB container via testcontainers — requires Docker) |
| `black .` | Format code (line-length 100) |
| `ruff check .` | Lint (rules: E, F, I, N, W) |
| `mypy lokilinux/` | Type check (strict mode) |

### Agent (`agent/`, or via root `Makefile`)

| Command | Description |
|---------|-------------|
| `make agent-build` | Build static `linux/amd64` binary (`CGO_ENABLED=0`) to `agent/bin/lokilinux-agent` |
| `make agent-build-arm64` | Build static `linux/arm64` binary |
| `make agent-package` | Build both arches, bundle with `scripts/loki-cli.sh`, produce `.tar.gz` (and `.deb`/`.rpm` if `nfpm` is installed) |
| `make agent-test` | `go test ./... -v -race -cover` |
| `go build ./...` | Plain build without the version ldflags root Makefile sets |
| `gofmt -l .` | Check formatting (run from `agent/`) |

### Frontend (`frontend/`)

| Command | Description |
|---------|-------------|
| `npm install` | Install dependencies |
| `npm run dev` | Dev server with HMR on `:3000` |
| `npm run build` | Production build (`nuxi build`) |
| `npm run preview` | Preview a production build locally |
| `npm run generate` | Static site generation (`nuxi generate`) |
| `npm run test` | Run tests once (`vitest run`) |
| `npm run test:coverage` | Run tests with coverage report |

### Root (`Makefile`, whole stack)

| Command | Description |
|---------|-------------|
| `make up` | Start production stack (`docker compose up -d`) |
| `make dev` | Start dev stack (hot-reload, bind mounts, local ports, no resource limits) |
| `make down` | Stop all containers |
| `make build` | Build all Docker images |
| `make logs` | Tail logs for all services |
| `make ps` | Show container status |
| `make init` | First-run: certs + volumes + migrations + admin user |
| `make certs` | Generate CA + server + agent mTLS certificates |
| `make proto` | Regenerate Go + Python code from `proto/lokilinux.proto` (requires `protoc`) |

## Code Style

- **Backend (Python):** [Black](https://black.readthedocs.io/) (line-length 100) and [Ruff](https://docs.astral.sh/ruff/) (rule sets E, F, I, N, W), configured in `backend/pyproject.toml`. Type checking via `mypy` in strict mode. Run with:
  ```bash
  cd backend
  black . && ruff check . && mypy lokilinux/
  ```
- **Agent (Go):** Standard `gofmt` formatting; no `golangci-lint` config is checked in. Run `gofmt -l .` and `go vet ./...` from `agent/` before submitting changes. `make agent-test` runs with `-race`, so data races fail the build.
- **Frontend (TypeScript/Vue):** No ESLint or Prettier config is currently checked into `frontend/`. Follow the existing formatting in the file you're editing (2-space indent, single quotes, no semicolons, matching the rest of the codebase) until a formatter config is added.

## Branch Conventions

No branch naming convention or CI enforcement is documented in this repository. Use descriptive branch names (e.g., `feature/agent-plugin-cache`, `fix/heartbeat-timeout`) and target `main` for pull requests.

## PR Process

No `.github/PULL_REQUEST_TEMPLATE.md` or CI workflows are present in this repository. Before opening a pull request:

- Run the relevant service's lint/type-check/test commands from the tables above for anything you touched.
- For backend changes that alter models, generate and include an Alembic migration (`alembic revision --autogenerate -m "..."`).
- For proto changes, run `make proto` and commit the regenerated `agent/gen/` and `backend/lokilinux/gen/` output alongside the `.proto` change.
- Keep PRs scoped to one service where possible — backend, agent, and frontend changes review more easily in isolation.
