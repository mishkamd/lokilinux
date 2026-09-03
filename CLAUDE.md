# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LokiLinux — an enterprise Linux operations control plane (fleet, patching, CVEs, compliance/drift,
workflow + Ansible automation, PKI/KMS, observability) for 10K–100K+ hosts. Four codebases in one repo:

| Path | Stack | Role |
|---|---|---|
| `backend/` | FastAPI 0.138 / Python 3.11 | REST `:8000`, gRPC `:50051`, 19 NATS/asyncio workers, business logic |
| `agent/` | Go 1.24, static CGO-free binary | Runs on managed hosts: heartbeat, inventory, jobs, 24 compliance collectors |
| `services/compliance/` | Go 1.25 (pgx, cel-go, JetStream) | CPU-bound compliance hot path (ingest → drift → CEL rules → scoring) |
| `frontend/` | Nuxt 4.5 / Vue 3.5 / TS | UI **and** the identity provider (Better Auth) |

Full product/feature/infra reference: [README.md](README.md). Per-module deep dives (RO):
[docs/modules/](docs/modules/). Compliance spec series (EN): [docs/compliance/](docs/compliance/).
Domain vocabulary (CVE vs Finding vs Open Exposure, etc.): [CONCEPTS.md](CONCEPTS.md).
Design tokens / UI system: [DESIGN.md](DESIGN.md).

## Commands

### Stack

```bash
make init          # first run only: certs → build → up → migrate → admin user
make up            # production stack, detached
make dev           # hot-reload stack (docker-compose.dev.yml override, infra ports exposed)
make down / logs / ps
make certs         # regenerate CA + mTLS server cert
```

### Tests

```bash
make agent-test        # cd agent && go test ./... -race -cover
make compliance-test   # cd services/compliance && go test ./... -race -cover
cd backend && .venv/bin/pytest tests/          # full Python suite
cd frontend && npm test                        # vitest run
```

Single test:

```bash
cd backend && .venv/bin/pytest tests/unit/test_job_signing.py::test_sign_and_verify -v
cd agent && go test ./internal/security/ -run TestEnvelope -race -v
cd frontend && npx vitest run stores/servers.test.ts
```

**Backend tests require a working Docker daemon and `backend/.env`.** `tests/conftest.py` starts a real
TimescaleDB container and runs `alembic upgrade head` **at import time**, before any `lokilinux.*` import,
because `Settings()` is instantiated at several modules' import time. A missing `.env` or dead Docker
fails collection, not an individual test. Each test gets a SAVEPOINT-wrapped session rolled back after.

### Lint / types

`black` and `ruff` at line-length 100, `ruff` selects `E,F,I,N,W`, `mypy` in `strict` mode (config in
`backend/pyproject.toml`). Frontend type check: `npx vue-tsc --noEmit`.

### LSP sidecars (agent tooling, not part of the app stack)

`docker-compose.lsp.yml` runs idle `lokilinux-lsp-ts` (typescript-language-server + vue-language-server)
and `lokilinux-lsp-go` (gopls) containers. The repo is bind-mounted at the same absolute path, so
language servers launched via `docker exec -i` (configured in `~/.config/opencode/opencode.jsonc` `lsp`)
resolve paths without mapping. Start with
`docker compose -f docker-compose.lsp.yml up -d --build`; warm the Go module cache once with
`go mod download` inside `lokilinux-lsp-go`.

### Build / release

```bash
make agent-build | agent-build-arm64 | agent-package   # agent binaries + .tar.gz/.deb/.rpm
make compliance-build
make proto                                              # regen Go + Python from proto/lokilinux.proto
make scan-image                                         # Trivy gate over lokilinux/* — fails on HIGH/CRITICAL
make sbom IMAGE=lokilinux/api:0.5.0
```

## Shipping a change — mandatory

**There is no hot-reload in the default stack.** Editing a file under `backend/`, `frontend/` or
`services/compliance/` does nothing to running containers until that service's image is rebuilt and
restarted. The Go agent is not containerized at all and is never touched by a docker build.

After any code change, use the `ship-changes` skill (`.claude/skills/ship-changes/`) instead of guessing:

```bash
.claude/skills/ship-changes/scripts/detect-changed-services.sh [base-branch]
```

Key facts it encodes: `backend/` maps to **three** compose services sharing one image
(`lokilinux-api`, `lokilinux-grpc`, `lokilinux-migrate`) — rebuild and restart them together;
`lokilinux-migrate` is a one-shot `alembic upgrade head` container, idempotent and always safe to run.
Agent releases go through `.claude/skills/ship-changes/scripts/release.sh <patch|minor|major>`
(dry-run first) — never straight to `make agent-package`.

Version bumps: use the `bump-version` skill. **Two independent version tracks** — `VERSION` (platform)
and `agent/VERSION` (agent). Never derive either from `git describe`: the repo carries interleaved tag
namespaces (`vX.Y.Z` platform, `X.Y.Z` agent) and describe will stamp the wrong one.

## Architecture: what you need to know before editing

### Agent ↔ control plane transport

The agent dials **out** over mTLS gRPC every 60s (`Manager.sendHeartbeat` →
`Manager.handleResponse` → `runJob`, `agent/internal/agent/manager.go`). Nothing ever connects
inbound to a managed host.

**Gotcha: the gRPC wire format is JSON, not protobuf.** Both sides register a JSON codec under the
name `"proto"` (`agent/internal/communication/grpc_client.go` `jsonCodec`, `backend/lokilinux/grpc_server.py`
`_from_json`/`_to_json`). `make proto` regenerates type definitions but does **not** change what goes on
the wire — a field added to `proto/lokilinux.proto` must be handled on both sides as plain JSON.
Swapping to binary protobuf means removing the codec registration on both sides at once.

**Gotcha: no capability negotiation exists in the heartbeat.** Feature gating is done by comparing the
reported `agent_version` against constants in `backend/lokilinux/utils/agent_capability.py`
(`MIN_AGENT_VERSION_NATIVE_MODULES`, `MIN_AGENT_VERSION_SIGNED_JOBS`). Any new agent-side job type must
bump the matching constant in the same change that ships the agent release, and must have a
compile-down fallback for older agents.

### Job security

Privileged jobs are Ed25519-signed envelopes (`backend/lokilinux/services/job_envelope.py` +
`job_signing.py`; verified in `agent/internal/security/envelope.go`, with replay and approval-claim
checks alongside). Cross-language compatibility is pinned by `envelope_crosslang_test.go` — changing
the canonical envelope encoding on one side breaks the fleet unless both are changed and that test
updated. Keys live behind a KMS provider Protocol (`backend/lokilinux/kms/`); only the file provider is
implemented, others `NotImplementedError` deliberately (see [docs/security/KMS.md](docs/security/KMS.md)).

### Where work belongs (Python vs Go)

The compliance split is deliberate: **FastAPI owns CRUD and read APIs; the Go service owns evaluation.**
Snapshots go gRPC servicer → NATS JetStream (`lokilinux.compliance.snapshot.{domain}`) →
`services/compliance/` (ingest → drift → CEL → scoring) → PostgreSQL, which the REST API then reads.
Don't add per-host CEL evaluation, drift diffing or scoring loops to the Python side.

Same rule generally: anything long-running is decoupled onto a NATS worker in `backend/lokilinux/workers/`
so REST stays fast. Topic names are a single source of truth in `backend/lokilinux/nats_topics.py` —
import the constants, never write raw subject strings.

### Object storage

Persistent files (generated reports, imported compliance datastreams, any future uploaded/exported
artifact) go through `backend/lokilinux/services/storage_service.py` into RustFS/S3 — never onto the
container filesystem and never as a new inline `BYTEA` column. `object_storage.py` is a thin boto3
wrapper business logic never imports directly; `storage_service.py` owns hashing, size limits, and the
category-prefix key layout (`CATEGORIES` dict — add a category there, never write a raw prefix string
at a call site). PostgreSQL's `storage_objects` table holds only metadata (SHA-256, size, bucket,
object key) — the row, not the bytes, is the source of truth for "does this exist".

**The deliberate exception**: signing/PKI keys (`backend/lokilinux/kms/`, policy-signing key,
CA key/cert) stay on local volumes — they're secret material with their own rotation/access model, not
artifacts. `inventory_blobs` also stays in Postgres — it's content-addressable and deduplicated
fleet-wide, sitting directly in the snapshot read path, where an S3 round-trip would be a regression.

New file-shaped data follows the dual-read pattern already used for `compliance_reports.body` →
`storage_object_id` (migration 046): add a nullable FK to `storage_objects`, write new rows through
`storage_service`, and keep reading the legacy column when the new one is `NULL` — no backfill
migration. Don't design a new sync/backfill migration; write dual-read and let old rows age out.

### Observability pipeline

Four chained workers, each a separate NATS consumer:
`EventProcessorWorker` (validate/dedup via Redis/fingerprint, batch → ClickHouse) →
`SignalProcessorWorker` (detector registry in `backend/lokilinux/signals/`) →
`CorrelationWorker` (weighted-window evaluator, Redis state, suppression) →
`IncidentWorker` (lifecycle, timeline, ClickHouse evidence) → runbooks, which can bridge into the
workflow engine only when `autorun_enabled` is set. ClickHouse (`backend/lokilinux/ch.py`) is
append-only storage with per-dataset retention env vars — never the source of truth for state.

### Auth & RBAC

Better Auth lives **inside the Nuxt app** and owns identity; the backend never stores passwords. FastAPI
validates Bearer JWTs via JWKS at `{BETTER_AUTH_URL}/api/auth/jwks`
(`backend/lokilinux/auth/jwks_validator.py`). Route protection is
`Depends(require_role("MANAGER", "OPERATOR", ...))` — **`ADMIN` always passes**, so never list it.
Better Auth ids are nanoids, not UUIDs: use `safe_user_uuid()` when writing to UUID columns.

Some routers are additionally plugin-gated with `require_plugin_enabled("<slug>")` (403 when the plugin
is disabled in `/plugins`) — the whole Ansible layer works this way.

### Frontend

- `/api/v1/**` is a Nitro same-origin proxy to the API container (`nuxt.config.ts` `routeRules`) — one
  public URL fronts both, so **never** hardcode an API base or issue cross-origin calls from a store.
- Everything under `components/ui`, `components/dashboard`, `components/workflow` is auto-imported with
  `pathPrefix: false` — `<Button>`, not `<UiButton>`.
- The frontend also talks to Postgres directly (Kysely, Better Auth tables) on `data-net`.
- Colors/typography/spacing come from [DESIGN.md](DESIGN.md); charts are Unovis, not Chart.js/Recharts.

### Docker networking

Five segmented networks, no flat network. `data-net`/`app-net`/`web-net` are `internal: true`; only
members of `gateway-net` can publish host ports (frontend 3000, api 8000/9090, grpc 50051). Redis, NATS,
ClickHouse, RustFS and pgBouncer are unreachable from the host — inspect them via `docker compose exec`.
Only the api has `egress-net` (NVD/CISA feeds, webhooks). Images are pinned to `${LOKILINUX_VERSION}`,
never `latest`. Adding a service means picking its networks explicitly.

**Gotcha confirmed live**: `lokilinux-migrate` must carry the same `image: lokilinux/api:${LOKILINUX_VERSION}`
tag as `lokilinux-api`/`lokilinux-grpc`/`lokilinux-ca-signer` — without it, Compose builds it under its
own implicit name and `docker compose build lokilinux-api` silently leaves migrate on a stale image, so
new migrations never apply. If a migration you just added doesn't seem to run, rebuild `lokilinux-migrate`
by name, don't assume rebuilding `lokilinux-api` covers it.

### Migrations

Alembic, sequentially numbered `NNN_name.py` under `backend/alembic/versions/` (currently through 037).
Applied by the one-shot `lokilinux-migrate` container, and again by `conftest.py` for tests.

## Conventions

- Conventional Commits with a scope matching the touched area: `feat(observability):`, `fix(agent):`,
  `fix(jobs):`, `docs(env):`.
- Deliberate simplifications are marked with a `ponytail:` comment naming the ceiling and the upgrade
  path — respect those; they are decisions, not omissions.
- CVE/Finding/Open Exposure have precise, non-interchangeable meanings — read `CONCEPTS.md` before
  touching vulnerability code. Severity is owned by the CVE, never by the Finding.
- `SECURITY_PROFILE=production` (independent from `ENVIRONMENT`, unset by default everywhere —
  neither `docker-compose.yml` nor `.env.example` sets it) makes startup fail closed (`main.py`
  lifespan) if job signing, certificate revocation or non-file KMS keys aren't configured. It's a
  deliberate, manual opt-in flag for the final step of the signed-jobs rollout
  ([EXECUTION_MODEL.md](docs/security/EXECUTION_MODEL.md)) — don't set it until the whole fleet is
  ready, and don't relax the checks themselves to make it boot.

## CodeGraph

`.codegraph/` exists — prefer `codegraph explore "<symbols or question>"` (or the `codegraph_explore`
MCP tool) over grep/find when locating or understanding code. One call returns verbatim source plus
call paths and blast radius.
