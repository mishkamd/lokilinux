<!-- generated-by: claude -->
# `lokilinux-compliance` — Go Microservice

## 1. Why a separate service instead of another FastAPI router

Snapshot ingest, per-domain diffing, CEL rule evaluation, and scoring are CPU-bound and run
once per agent per heartbeat cycle — at 100,000 agents on a 60s cadence that's up to ~1,700
evaluations/sec sustained, each potentially running dozens of rules. `asyncio` (the existing
backend's concurrency model) is fine for I/O-bound REST/CRUD but the wrong tool for that
workload; Go's goroutines plus a bounded worker pool are the same choice the existing agent
already made for its own collectors. Keeping it a separate process also means a spike in
compliance load never starves the `lokilinux-api` process that serves the UI and RBAC/auth.

It is **not** a second API. It has no auth, no public REST, no direct frontend traffic — only
`/healthz` and `/metrics` (Prometheus, matching the platform's existing metrics port
convention on `lokilinux-api:9090`). Fiber is used for those two routes only, per the stack
listed in CLAUDE.md for new Go services.

## 2. Package structure

```
services/compliance/                      # new top-level dir, sibling to backend/ and agent/
├── cmd/compliance/main.go                 # entrypoint: config, NATS conn, Postgres pool, Fiber healthz, run()
├── go.mod                                 # module github.com/lokilinux/compliance
├── internal/
│   ├── config/config.go                  # YAML + env, mirrors backend Settings() shape
│   ├── ingest/
│   │   ├── consumer.go                   # JetStream durable consumer, one per domain-hash-changed subject
│   │   ├── snapshot.go                   # canonicalize + BLAKE3 + upsert inventory_blobs/inventory_snapshots
│   │   └── delta.go                       # diff prev vs new canonical doc -> inventory_deltas row
│   ├── baseline/
│   │   ├── resolver.go                   # scope-tree merge -> baseline_effective (D5)
│   │   └── signer.go                      # Ed25519 sign/verify on publish
│   ├── rules/
│   │   ├── engine.go                      # Evaluator interface + CEL implementation
│   │   ├── cel_env.go                     # CEL environment: declares fact-document variables, custom functions
│   │   └── coverage.go                    # OVAL_UNMAPPED tracking, coverage % computation
│   ├── drift/
│   │   ├── detector.go                    # 3-way compare: current vs baseline, vs previous, vs desired
│   │   └── rootcause.go                   # correlates drift timestamp against jobs/audit_logs for root_cause
│   ├── scoring/scorer.go                  # per-category score computation -> compliance_scores
│   ├── scheduler/
│   │   ├── leader.go                     # NATS KV-based leader election among replicas
│   │   ├── cron.go                       # scan cadence + maintenance window + Job.scheduled_time dispatch (D8)
│   │   └── sweep.go                       # periodic full-fleet drift sweep trigger
│   ├── storage/
│   │   ├── postgres.go                   # pgx pool, matches backend pool_size=20 conventions
│   │   └── queries/*.sql                 # sqlc-generated query definitions
│   └── telemetry/metrics.go              # Prometheus collectors
└── Makefile                               # build/test targets mirroring agent/Makefile conventions
```

## 3. Core interfaces

```go
// internal/rules/engine.go
package rules

import "context"

// Evaluator checks one compliance rule against a fact document and returns a verdict.
// CEL is the only production implementation; OVAL/oscap is out of scope but the interface
// leaves room for a future OscapEvaluator without touching call sites.
type Evaluator interface {
	Evaluate(ctx context.Context, rule Rule, facts map[string]any) (Verdict, error)
}

type Rule struct {
	ID         string
	CheckExpr  string // CEL source, empty if CheckSource == OVALUnmapped
	CheckSource CheckSource
}

type CheckSource string

const (
	CheckSourceCEL           CheckSource = "CEL"
	CheckSourceOVALUnmapped  CheckSource = "OVAL_UNMAPPED"
	CheckSourceOscapFallback CheckSource = "OSCAP_FALLBACK"
)

type Verdict struct {
	Result      Result // PASS/FAIL/ERROR/NOT_APPLICABLE/NOT_EVALUATED
	ActualValue any
	Evidence    map[string]any
	Err         error
}

type Result string

const (
	ResultPass          Result = "PASS"
	ResultFail          Result = "FAIL"
	ResultError         Result = "ERROR"
	ResultNotApplicable Result = "NOT_APPLICABLE"
	ResultNotEvaluated  Result = "NOT_EVALUATED"
)
```

```go
// internal/drift/detector.go
package drift

import "context"

// Detector runs the three brief-mandated comparisons for one agent snapshot.
type Detector interface {
	CompareToBaseline(ctx context.Context, agentID string, domain string) ([]Event, error)
	CompareToPrevious(ctx context.Context, agentID string, domain string) ([]Event, error)
	CompareToDesired(ctx context.Context, agentID string, domain string) ([]Event, error)
}

type Event struct {
	Domain      string
	Severity    Severity
	ChangeType  ChangeType
	Summary     string
	FieldDiffs  []FieldDiff
	RootCause   *RootCause // nil if undetermined
}

type Severity string

const (
	SeverityLow      Severity = "LOW"
	SeverityMedium   Severity = "MEDIUM"
	SeverityHigh     Severity = "HIGH"
	SeverityCritical Severity = "CRITICAL"
)

type ChangeType string

const (
	ChangeTypeFileChanged       ChangeType = "FILE_CHANGED"
	ChangeTypePackageChanged    ChangeType = "PACKAGE_CHANGED"
	ChangeTypeKernelChanged     ChangeType = "KERNEL_CHANGED"
	ChangeTypeServiceDisabled   ChangeType = "SERVICE_DISABLED"
	ChangeTypeConfigModified    ChangeType = "CONFIG_MODIFIED"
	ChangeTypeFirewallModified  ChangeType = "FIREWALL_MODIFIED"
	ChangeTypeUserAdded         ChangeType = "USER_ADDED"
	ChangeTypeUserRemoved       ChangeType = "USER_REMOVED"
	ChangeTypePermissionChanged ChangeType = "PERMISSION_CHANGED"
	ChangeTypeRepositoryChanged ChangeType = "REPOSITORY_CHANGED"
	ChangeTypeSELinuxChanged    ChangeType = "SELINUX_CHANGED"
	ChangeTypeSysctlChanged     ChangeType = "KERNEL_PARAMETER_CHANGED"
	ChangeTypeSystemdOverride   ChangeType = "SYSTEMD_OVERRIDE_CHANGED"
)

type FieldDiff struct {
	FieldPath string
	OldValue  any
	NewValue  any
}

// RootCause is best-effort: correlate the drift timestamp window against Jobs
// (did a LokiLinux job touch this agent recently?) and audit_logs (did a user
// change a policy/baseline that would explain it?). Nil means "unknown" —
// never fabricated.
type RootCause struct {
	Source string // "job" | "policy_change" | "unknown"
	JobID  *string
	UserID *string
}
```

```go
// internal/baseline/resolver.go
package baseline

import "context"

// Resolver computes the effective baseline for an agent by merging all
// matching baseline scopes, most-specific wins (D5). Pure function of
// (agent attributes, published baseline versions) — safe to recompute anytime,
// baseline_effective is a cache, not a source of truth.
type Resolver interface {
	Resolve(ctx context.Context, agentID string) (Effective, error)
}

type Effective struct {
	AgentID            string
	BaselineVersionIDs []string // ordered GLOBAL -> OS -> ROLE -> ENVIRONMENT -> DATACENTER -> CLUSTER -> APPLICATION
	MergedState        map[string]any
	MergedHash         string
}
```

## 4. Scheduler (D8) — the new primitive

No scheduler exists anywhere in this codebase today (`Job.scheduled_time` is written by
`routers/jobs.py` but nothing ever reads it — confirmed by grep across `backend/lokilinux/`
for `apscheduler`/`celery`/`croniter`). Rather than bolt a second, competing scheduler onto
FastAPI, this module builds the one scheduler LokiLinux needs, in the Go service, and it also
serves `Job.scheduled_time` dispatch as a side effect.

```go
// internal/scheduler/leader.go
package scheduler

// Leader election via NATS KV compare-and-swap (JetStream KV bucket "compliance-leader").
// Every replica attempts to acquire a TTL'd key on startup and renews it; only the leader
// runs cron.go and sweep.go. Followers stay in the JetStream consumer group for ingest,
// which scales independently of leadership.
type LeaderElector struct {
	kv       KVStore // wraps nats.KeyValue
	ttl      time.Duration
	nodeID   string
}

func (l *LeaderElector) Campaign(ctx context.Context) (isLeader <-chan bool) { /* ... */ }
```

```go
// internal/scheduler/cron.go — runs only on the elected leader
package scheduler

// Responsibilities:
//  1. Per-policy-set scan cadence (policy_assignments has no interval column by design —
//     cadence is a compliance.* setting, default 4h, overridable per scope_selector).
//  2. Maintenance window gating for remediation_plans awaiting execution.
//  3. Job.scheduled_time dispatch: poll jobs WHERE status='SCHEDULED' AND scheduled_time <= now(),
//     transition to QUEUED so the existing agent heartbeat pull-path picks them up — this is
//     the first consumer that table column has ever had.
//  4. Fleet-wide drift sweep trigger (compares latest snapshot vs baseline for agents that
//     haven't drifted-checked in > sweep_interval, catching agents whose heartbeat delta-sync
//     never flagged a change but whose baseline itself was just republished).
```

## 5. Worker pool sizing (ingest side)

JetStream consumer for `lokilinux.compliance.snapshot.*` (D2/04-PROTOCOL.md) uses queue-group
subscription so replicas load-balance automatically; each replica runs a bounded worker pool
(`runtime.NumCPU() * 4` workers, matching Go's typical I/O-bound-with-CPU-bursts sizing) pulling
from an internal channel, not one goroutine per message — bounds memory under a thundering-herd
heartbeat cycle (all agents reporting near the top of their 60s window).

## 6. Dependencies

| Package | Purpose |
|---|---|
| `github.com/nats-io/nats.go` | JetStream consumer/producer, KV for leader election |
| `github.com/jackc/pgx/v5` | Postgres driver + pool |
| `github.com/google/cel-go` | Rule evaluation (D4) |
| `lukechampine.com/blake3` | Snapshot/blob hashing, matches agent-side choice |
| `github.com/klauspost/compress/zstd` | Blob compression |
| `golang.org/x/crypto/ed25519` (stdlib `crypto/ed25519`) | Baseline signing |
| `github.com/gofiber/fiber/v2` | `/healthz`, `/metrics` only |
| `github.com/prometheus/client_golang` | Metrics |

No ORM — `sqlc` generates typed query functions from `internal/storage/queries/*.sql` against
the schema in [01-DATA-MODEL.md](01-DATA-MODEL.md), keeping the Go side schema-verified at
build time without duplicating SQLAlchemy models.

## 7. Deployment shape

New `lokilinux-compliance` service in `docker-compose.yml`, same pattern as `lokilinux-grpc`:
own container, shares Postgres (via pgbouncer) and NATS with the rest of the stack, no volume
mounts beyond nothing (stateless). Horizontal scaling = more replicas behind the same
JetStream queue group; only one becomes scheduler leader at a time. Full deployment manifest
in [13-OPS.md](13-OPS.md).
