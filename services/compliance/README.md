# LokiLinux Compliance Service

Go microservice owning the **CPU-bound compliance hot path**: snapshot ingest, drift detection, CEL rule evaluation, scoring, baseline resolution and assessment scheduling. Deliberately split out of the FastAPI control plane so heavy evaluation never blocks REST latency.

Companion docs: [root README](../README.md) · [control plane](../../backend/README.md) · [agent (collector side)](../../agent/README.md).

## Identity & Properties

| Property | Value |
|---|---|
| Language | Go 1.25 |
| DB driver | pgx/v5 5.9 (`pgxpool`, transactional `dbtx` surface shared by pool & tx — `internal/storage/postgres.go`) |
| Rule engine | cel-go 0.22 (CEL expressions over canonical compliance facts) |
| Messaging | nats.go 1.39 with **JetStream** consumer (durable) |
| Container | distroless static image, `USER nonroot:nonroot` |
| Version stamping | `-ldflags "-X main.Version=…"` from compose build arg `VERSION=${LOKILINUX_VERSION}` |

## Architecture

```text
                       NATS JetStream
  lokilinux-grpc ──publish──► lokilinux.compliance.snapshot.{domain}
                                      │
                     ┌────────────────▼─────────────────┐
                     │      lokilinux-compliance        │
                     │                                  │
   JetStream durable └─► ingest.Consumer              │
                         • EnsureStream (idempotent     │
                           CreateOrUpdateStream)       │
                         • domain dispatch per snapshot │
                         • policy-set rule bucketing    │
                         • file-integrity ingestion     │
                         • assessment trigger            │
                       rules.engine ── CEL evaluate      │
                       scoring       ── pass/fail/na      │
                       drift         ── field-level diff vs baselines + FIM
                       baseline      ── resolver: published baselines per agent,
                                          merge → Effective; consumes
                                          lokilinux.compliance.baseline.published
                       scheduler     ── leader-only pollers via NATS KV
                                          (bucket compliance-leader)
                       storage       ── pgx writes:
                                          compliance_scores (+ daily aggregates),
                                          drift tables, rule evaluations
                     └────────────────┬─────────────────┘
                                      ▼
                    PostgreSQL/TimescaleDB (via pgBouncer)
          results read back by FastAPI /api/v1/compliance/* routers
```

Important flow property: **results go to PostgreSQL directly** — there are no `drift.detected` / `score.updated` NATS events in the current source. The only inbound subjects are the snapshot stream and `lokilinux.compliance.baseline.published`.

## Directory Map

```text
services/compliance/
├── cmd/compliance/main.go   # Entry point; flags: -version, -healthcheck (-healthcheck-port)
├── internal/
│   ├── config/              # YAML config + applyDefaults; env overrides for secrets/URLs
│   ├── ingest/              # JetStream consumer, Ingester, per-domain dispatch,
│   │                        #   file_integrity.go, assessment trigger/bucketing
│   ├── drift/               # Field-level drift detection against effective baselines
│   ├── rules/engine.go      # CEL expression engine over normalized facts
│   ├── scoring/scoring.go   # Score computation (passed/failed/not-applicable rollups)
│   ├── baseline/            # Resolver (published baselines → agent-effective set),
│   │                        #   consumer of baseline.published events
│   ├── policy/              # Policy-set handling on the hot path
│   ├── hashing/             # Content-hash helpers matching agent-side canonicalization
│   ├── scheduler/           # AssessmentPoller etc. — gated by LeadershipChecker (NATS KV),
│   │                        #   atomic claim strategy
│   ├── scope/               # Scope evaluation (agent targeting/attributes)
│   └── storage/postgres.go  # pgxpool Store — all SQL lives here (dbtx pool/tx abstraction)
├── Dockerfile               # Multi-stage → gcr.io/distroless/static-debian12
└── go.mod                   # Go 1.25 module
```

## Configuration

Runs on **env vars + defaults alone** in the compose deployment — no `compliance.yaml` is mounted (`internal/config/config.go` still supports a YAML file for bare-metal runs).

| Env var | Purpose |
|---|---|
| `DATABASE_URL` | **Keyword/value DSN form**, not a URI (see quirk below). Compose sets `host=pgbouncer port=5432 user=… password=… dbname=…` |
| `NATS_URL` | `nats://user:pass@nats:4222` (broker requires auth) |
| `LOG_LEVEL` | Structured log level |

### The DSN keyword-form quirk (deliberate)

Compose passes `POSTGRES_PASSWORD` as a keyword=value DSN because generated secrets may contain `/`, `=`, `+` — characters that a `postgresql://` URI parser treats as delimiters and that would need percent-encoding. This was confirmed by a real hang (`context deadline exceeded` on `Ping`) when the URI form was used with such a password. Keep the keyword form.

## Healthcheck (distroless constraint)

The runtime image is distroless: **no shell, no wget/curl**. The binary therefore implements its own probe:

```text
/lokilinux-compliance -healthcheck [-healthcheck-port 8080]
```

which performs an internal HTTP GET to its own `/healthz`. This is wired as the compose healthcheck command — using any shell-based check crash-loops the container (`wget: executable file not found in $PATH`), a failure mode hit and documented during the first real deployment.

## Deployment

```bash
# From repo root
make compliance-build     # compile
make compliance-test      # run test suite
make up                   # full stack (service is part of docker-compose.yml)
```

Service topology in compose:

- networks: `app-net` only (reaches pgBouncer + NATS; no ingress)
- depends_on: pgbouncer healthy, nats healthy, migrate completed successfully
- hardening: `read_only` rootfs + tmpfs `/tmp`, `cap_drop: ALL`, no-new-privileges, resource limits
- **no published ports**

## Testing

```bash
cd services/compliance
go test ./...
```

Unit tests cover each internal package (`ingest`, `drift`, `rules`, `scoring`, `baseline`, `scheduler`, `scope`, `storage`, `config`, `hashing`), including integration-style tests for the JetStream ingest path.
