<!-- generated-by: gsd-doc-writer -->
# Testing

LokiLinux has three independent test suites — backend (pytest), agent (Go), and frontend (vitest) — each run from its own subdirectory. There is no root-level test command that runs all three, and no CI workflow currently wired up (no `.github/workflows/` directory exists in this repo).

**Coverage is thin.** This doc documents what exists rather than an aspirational suite — see [Coverage reality check](#coverage-reality-check) below before relying on these suites as a regression safety net.

## Backend (pytest)

**Framework:** pytest 9.1.1 + pytest-asyncio 1.3.0 + pytest-cov 7.0.0, declared in `backend/pyproject.toml` under `[project.optional-dependencies].dev`.

**Setup:**

```bash
cd backend
pip install -e ".[dev]"
```

Tests require Docker to be running — `backend/tests/conftest.py` spins up a real `timescale/timescaledb:2.28.1-pg17` container via `testcontainers` for every test session, runs `alembic upgrade head` against it once, then wraps each test in a SAVEPOINT that's rolled back afterward (no manual DB setup needed, but Docker must be available). Redis and NATS are not containerized — `conftest.py` provides `FakeCache` (in-memory dict) and `FakeNats` (records published messages) fixtures instead, injected via FastAPI `dependency_overrides`.

**Running tests:**

```bash
cd backend
pytest tests/ -v --cov=lokilinux              # full suite
pytest tests/unit/ -v --cov=lokilinux          # unit tests only
pytest tests/integration/ -v                   # integration tests only
pytest tests/unit/test_job_service.py -v       # single file
```

`testpaths = ["tests"]` and `asyncio_mode = "auto"` are set in `backend/pyproject.toml` `[tool.pytest.ini_options]`, so async test functions don't need `@pytest.mark.asyncio` decorators.

**What exists today:**

| File | Type | Lines |
|------|------|-------|
| `tests/unit/test_agent_service.py` | unit | 325 |
| `tests/unit/test_job_service.py` | unit | 106 |
| `tests/unit/test_agent_install.py` | unit | 66 |
| `tests/integration/test_jobs_router.py` | integration | 115 |
| `tests/integration/test_servers_router.py` | integration | 114 |
| `tests/integration/test_cves_router.py` | integration | 46 |
| `tests/integration/test_policies_router.py` | integration | 64 |

Integration tests use the `client` fixture (`AsyncClient` over an `ASGITransport`-mounted FastAPI app with only `api_v1_router` included) and override `get_db`, `get_cache`, `get_nats`, and `get_current_user` — auth is bypassed with a fixed `current_user` fixture (`role: ADMIN`), so these tests do not exercise the Better Auth session-validation path.

**Gaps:** `backend/lokilinux/api/v1/routers/` has 14 router modules (`admin`, `agent_install`, `alerts`, `ansible_projects`, `ansible_roles`, `categories`, `dashboard`, `jobs`, `playbook_templates`, `playbooks`, `plugins`, `policies`, `servers`, `cves`) — only 4 (`jobs`, `servers`, `cves`, `policies`) have integration test coverage. There are no tests for the gRPC server (`lokilinux/api/grpc/agent_service.py`), any of the 8 NATS workers, or the auth/session-validation code in `lokilinux/auth/`.

**Writing new tests:** Follow the existing naming convention — `test_<subject>.py` under `tests/unit/` for logic that doesn't need the DB/HTTP layer, or `tests/integration/` for anything going through the `client` fixture. Reuse the `db_session`, `fake_cache`, `fake_nats`, and `current_user` fixtures from `conftest.py` rather than building new mocks.

**Coverage requirements:** No coverage threshold is configured — `pytest-cov` is installed and `--cov=lokilinux` produces a report, but nothing in `pyproject.toml` or a CI step enforces a minimum percentage.

## Agent (Go)

**Framework:** standard library `testing` package — no third-party test framework or assertion library.

**Running tests:**

```bash
make agent-test
# equivalent to: cd agent && go test ./... -v -race -cover
```

This runs with the race detector and coverage reporting enabled by default (see `agent-test` target in the root `Makefile`).

**What exists today:**

| File | Package |
|------|---------|
| `agent/internal/agent/manager_test.go` | `agent` (heartbeat backoff logic) |
| `agent/internal/communication/grpc_client_test.go` | `communication` |
| `agent/internal/modules/plugin_installer_test.go` | `modules` |
| `agent/internal/modules/system_info_test.go` | `modules` |

**Gaps:** the agent has 13 non-test `.go` source files across `internal/agent`, `internal/communication`, `internal/config`, `internal/modules`, and `internal/storage`. `internal/config/config.go`, `internal/storage/sqlite.go` (the local SQLite cache), and `internal/modules/ansible_executor.go`, `job_executor.go`, `metrics.go`, `package_manager.go`, `vulnerability.go` have no test files.

**Writing new tests:** Follow Go convention — `<file>_test.go` in the same package as the code under test, using table-driven tests where practical (see `manager_test.go` for the existing pattern).

**Coverage requirements:** None configured — `-cover` prints a summary but nothing enforces a threshold.

## Frontend (vitest)

**Framework:** vitest 4.1.9 with `@nuxt/test-utils` (Nuxt-aware environment) and `@vue/test-utils`, declared in `frontend/package.json` `devDependencies`. Config is `frontend/vitest.config.ts`, which sets `test.environment: 'nuxt'` via `defineVitestConfig` from `@nuxt/test-utils/config`.

**Running tests:**

```bash
cd frontend
npm install
npm run test              # vitest run
npm run test:coverage     # vitest run --coverage
```

There is no watch-mode script defined in `package.json` — run `npx vitest` directly for watch mode if needed.

**What exists today:**

| File | Lines | Covers |
|------|-------|--------|
| `stores/servers.test.ts` | 84 | Pinia `servers` store |
| `pages/servers/id.page.test.ts` | 81 | Server detail page |
| `utils/agentPackages.test.ts` | 55 | `buildPackageCards` helper |

**Gaps:** this covers a small slice of the frontend — one Pinia store, one page, one utility. The Better Auth integration (`frontend/server/utils/auth.ts`), other Pinia stores, and the majority of Vue components/pages have no test coverage.

**Writing new tests:** existing tests use `describe`/`it`/`expect` from `vitest` directly (no custom test helpers or shared setup file present). Co-locate new `*.test.ts` files next to the code they cover, matching the pattern in `stores/servers.test.ts` and `utils/agentPackages.test.ts`.

**Coverage requirements:** None configured in `vitest.config.ts` — `test:coverage` produces a report but nothing enforces a minimum.

## CI integration

No CI configuration exists in this repository — there is no `.github/workflows/` directory. None of the three suites above currently run automatically on push or pull request; all commands must be run manually.

## Coverage reality check

- **Backend:** 4 of 12 API routers have integration tests; core services (agent, job) have unit tests; gRPC server and all 8 NATS workers are untested.
- **Agent:** 4 of 7 source files have tests; the SQLite local cache and job/ansible/vulnerability execution modules are untested.
- **Frontend:** 3 test files total, covering one store, one page, and one utility — the vast majority of components and the Better Auth flow are untested.
- **No CI enforcement** — nothing currently blocks a merge on test failure or coverage regression.

Treat these suites as spot checks on specific modules, not as a safety net for the codebase as a whole.
