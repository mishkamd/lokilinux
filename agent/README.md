# LokiLinux Agent

Go daemon installed on every managed Linux server. Connects **outbound-only** to the control plane over mTLS gRPC, reports inventory/health/vulnerabilities/compliance hashes every heartbeat, executes jobs, playbooks, remediation plans and workflow steps. Ships as a static binary (CGO disabled) plus an optional privileged-action **exec broker** for non-root operation.

Companion docs: [root README](../README.md) · [control plane](../backend/README.md) · [compliance service](../services/compliance/README.md).

## Identity & Properties

| Property | Value |
|---|---|
| Language | Go 1.24 (`go.mod`: toolchain go1.24.13) |
| Binary | Static, `CGO_ENABLED=0`, linux/amd64 + linux/arm64 |
| Version SSOT | `agent/VERSION` (currently `0.37.0`) — consumed by Makefile, `.env AGENT_VERSION` and the release script |
| SQLite cache | `modernc.org/sqlite` — pure Go, no cgo |
| Key derivation | `lukechampine.com/blake3` (package delta-sync checksums, content hashing) |
| Transport | gRPC bidirectional stream, **JSON codec**, mutual TLS |
| Packaging | nfpm: `.tar.gz` + `.deb` + `.rpm` for both arches (`make agent-package`) |

## Heartbeat Architecture

```text
┌───────────────────────────────────────────────────────────────┐
│                         agent host                            │
│                                                               │
│  loki-agent (manager loop — internal/agent/manager.go)        │
│    every Heartbeat.IntervalSec (default 60s):                 │
│      ├─ collect system info + health metrics                  │
│      ├─ package list — delta-synced via SHA-256 checksums     │
│      ├─ vulnerabilities (dnf/yum CVE cross-reference today;   │
│      │   Debian/Ubuntu sources on roadmap)                    │
│      ├─ compliance runner → 24 collectors, per-domain         │
│      │   canonical JSON → BLAKE3 domain hashes                │
│      └─ send HeartbeatStream msg over mTLS gRPC               │
│           payload: system_status, packages, health, job       │
│           results, vulnerabilities, agent_version,            │
│           domain_hashes (+ domain_full when resynced)         │
│                                                               │
│  response from control plane:                                 │
│      pending_jobs (max 10/round-trip, approval-gated)         │
│      + resync_domains → next heartbeat carries full bodies    │
│                                                               │
│  loki-agent-exec (optional broker daemon — exec-broker/)      │
│      unix socket authenticated via SO_PEERCRED                │
│      allowlisted privileged operations only                   │
└──────────────────────────┬────────────────────────────────────┘
                           │ outbound mTLS :50051 only
                           ▼
                 lokilinux-grpc (control plane)
```

No inbound ports are opened. If the platform is unreachable, the agent retries with capped backoff (`Heartbeat.RetryBackoffMax`) and keeps working locally from its SQLite cache.

## Directory Map

```text
agent/
├── cmd/
│   ├── agent/main.go          # Agent entry point (-config /etc/lokilinux/agent.yaml)
│   └── exec-broker/           # Exec-broker daemon entry point
├── exec-broker/               # Broker implementation:
│   ├── server.go              #   unix socket listener + SO_PEERCRED peer identity
│   ├── operations.go          #   allowlisted privileged ops (safe subset)
│   ├── client.go              #   in-process client used by the agent modules
│   └── server_test.go
├── internal/
│   ├── agent/                 # Manager: heartbeat loop, job dispatch, dispatch wiring
│   │   └── manager.go         #   interval/timeout from config (job_execution.timeout_seconds)
│   ├── communication/         # mTLS gRPC client, stream lifecycle, reconnection
│   ├── compliance/            # Compliance hot path (agent side):
│   │   ├── collector.go       #   Collector interface + domain model
│   │   ├── runner.go          #   NewRunner(registry…) — runs all, hash per domain
│   │   ├── canonical.go       #   Canonical JSON normalization before hashing
│   │   └── *_collector.go     #   24 collectors, each with a test twin
│   ├── security/              # Signed-job trust model:
│   │   ├── envelope.go        #   Ed25519 envelope verify (+ cross-language tests vs Python KMS)
│   │   ├── policy.go          #   enforce_signed_jobs staged rollout gate
│   │   ├── replay.go          #   replay protection
│   │   ├── approval_claim.go  #   approval claim tokens
│   │   └── capabilities.go    #   capability negotiation
│   ├── broker/                # Client side of exec-broker (operations routing)
│   ├── modules/               # Job executors:
│   │   ├── job_executor.go    #   COMMAND jobs
│   │   ├── package_manager.go #   PACKAGE jobs (apt/dnf/yum family), package_updater.go
│   │   ├── service.go         #   SERVICE jobs
│   │   ├── file.go            #   FILE jobs
│   │   ├── ansible_executor.go#   ANSIBLE playbooks (argv-only, systemd transient unit,
│   │   │                      #     --connection=local, snapshot-based content)
│   │   ├── remediation_executor.go # REMEDIATION via broker-backed ActionRunners
│   │   │                      #     (dry-run stays local)
│   │   ├── workflow_steps_executor.go # coalesced WORKFLOW_STEPS payloads
│   │   ├── plugin_installer.go#   plugin drop-in install (+ signature check)
│   │   ├── python_executor.go #   PYTHON jobs (sandbox profile tested)
│   │   ├── reboot.go          #   REBOOT with graceful handling
│   │   ├── metrics.go         #   metric.sample emission into heartbeat
│   │   └── system_info.go     #   OS/hardware inventory collection
│   ├── logredact/redact.go    # Redaction of secrets/patterns from logs
│   ├── storage/               # SQLite cache (packages state, offline retention)
│   └── config/config.go       # agent.yaml schema (struct mirrors below)
├── packaging/
│   └── loki-agent-exec.service# systemd unit for the optional broker daemon
├── .nfpm.yaml                 # Package layout: /usr/local/bin/lokilinux-agent + loki-agent-exec
└── VERSION                    # Build-side version source of truth (0.37.0)
```

### The 24 compliance collectors

auditd · capabilities · certificates · container runtime · cron · file integrity · firewall · kernel · kernel modules · login.defs · mounts · network · open ports · PAM · password policy · processes · repositories · SELinux · sshd · sudo · sysctl · systemd services · time sync · users.

Each collector normalizes facts to canonical JSON (`canonical.go`) and the runner computes one BLAKE3 content hash per domain — heartbeats carry only these hashes; full bodies go up only for domains whose hash drifted (server-driven `resync_domains`). Tests exist per collector (`*_test.go`).

## Configuration — `/etc/lokilinux/agent.yaml`

Schema mirrors `internal/config/config.go`:

| Section | Keys | Purpose |
|---|---|---|
| `platform` | `url`, `grpc_endpoint` | Control plane endpoints |
| `identity` | `agent_id`, `cert_path`, `key_path`, `ca_path` | mTLS material issued at enrollment |
| `heartbeat` | `interval_sec`, `timeout_sec`, `retry_backoff_max` | Loop cadence and backoff cap |
| `cache` | `enabled`, `path`, `sqlite_db`, `retention_days` | Local SQLite cache |
| `job_execution` | `max_parallel_jobs`, `timeout_seconds`, `sandbox_enabled` | Executor limits |
| `security` | `enforce_signed_jobs`, `signing_pub_key_path`, (versioned key set) | Staged signed-jobs rollout: `false` = accept unsigned privileged jobs with WARN, `true` = reject without valid Ed25519 envelope. Public key arrives at enrollment via `/agent/signing-key`; key rotation uses a versioned trust map |
| `logging` | level/format settings | Structured logging via `logredact` |
| `file_integrity` | FIM paths/options | Feeds the file-integrity collector |

Example:

```yaml
platform:
  url: https://lokilinux.example.com
  grpc_endpoint: lokilinux.example.com:50051
identity:
  cert_path: /etc/lokilinux/certs/agent.crt
  key_path: /etc/lokilinux/certs/agent.key
  ca_path: /etc/lokilinux/certs/ca.crt
heartbeat:
  interval_sec: 60
  timeout_sec: 30
security:
  enforce_signed_jobs: true
```

## Enrollment & Certificates

1. Admin/Operator generates an enrollment token (REST `/agent/install.sh` flow — token validated from Redis server-side).
2. The rendered installer registers the agent against `/agents/register` with the token.
3. Server returns agent identity: client certificate signed by the platform CA + CA bundle.
4. Heartbeats thereafter authenticate by mTLS; identity changes require re-enrollment proof-of-possession — server checks the CRL so revoked certificates cannot resurrect identities.

## Exec Broker (non-root operation)

Opt-in hardening mode:

- `loki-agent-exec` runs as a separate daemon (systemd unit provided at `packaging/loki-agent-exec.service`).
- Communication over a Unix socket; caller verified via socket peer credentials (`SO_PEERCRED`) — only the agent's UID is served.
- Operations are an explicit allowlist (`exec-broker/operations.go`): the unprivileged agent asks the broker to perform narrowly-scoped privileged actions (service management, package operations, remediation actions).
- Remediation executes through broker-backed ActionRunners; **dry-run stays local** and never touches the broker.
- Telemetry routing (`check_updates`) also flows through broker-aware paths when enabled.

## Build & Test

```bash
make agent-build          # static binary linux/amd64
make agent-build-arm64    # linux/arm64
make agent-package        # .tar.gz + .deb + .rpm (both arches, nfpm)
make agent-test           # go test ./... -race
```

Direct Go commands from `agent/`:

```bash
go build -o bin/lokilinux-agent ./cmd/agent
go vet ./... && go test -race ./...
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o bin/agent-arm64 ./cmd/agent
```

## Job Types Handled

| Job type | Module |
|---|---|
| `COMMAND` | `modules/job_executor.go` |
| `PACKAGE` | `modules/package_manager.go` (+ updater) |
| `SERVICE` | `modules/service.go` |
| `FILE` | `modules/file.go` |
| `PYTHON` | `modules/python_executor.go` (sandbox-profiled) |
| `ANSIBLE` | `modules/ansible_executor.go` — argv-only invocation through a systemd transient unit; roles/playbook content embedded in the job snapshot |
| `REMEDIATION` | `modules/remediation_executor.go` — broker-backed ActionRunners |
| `WORKFLOW_STEPS` | `modules/workflow_steps_executor.go` — multiple steps coalesced into one job per heartbeat round-trip |
| Plugin installs | `modules/plugin_installer.go` — signature-checked drop-ins |

Results are reported on the next heartbeat via `job_results`; the server aggregates per-job status (`COMPLETED` / `FAILED` / `TIMEOUT` / `PARTIALLY_COMPLETED`).
