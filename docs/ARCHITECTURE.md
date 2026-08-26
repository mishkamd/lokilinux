# LokiLinux — Architecture Reference (Full Stack Documentation)

**Version:** 0.1.0  
**Last updated:** 2026-08-06  
**Status:** Live — reflects deployed code at commit `9e77abb`

> **Notă (aug 2026):** de la acest snapshot codul a evoluat (Workflow Builder engine v0.3.0, commit `77c4220`). Documentația per modul, actualizată la starea curentă a codului, se află în [`docs/modules/`](modules/) — index: [`docs/modules/00-index.md`](modules/00-index.md).

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Infrastructure Topology](#2-infrastructure-topology)
3. [Control Plane — FastAPI Backend](#3-control-plane--fastapi-backend)
4. [Linux Agent — Go Daemon](#4-linux-agent--go-daemon)
5. [Frontend — Nuxt 4 + Vue 3](#5-frontend--nuxt-4--vue-3)
6. [Compliance & Drift Management](#6-compliance--drift-management)
7. [Communication Protocols](#7-communication-protocols)
8. [Authentication & Authorization](#8-authentication--authorization)
9. [Data Flow — End to End](#9-data-flow--end-to-end)
10. [Deployment & Operations](#10-deployment--operations)

---

## 1. Platform Overview

LokiLinux is an Enterprise Linux Operations Platform — a unified control plane for centralized fleet management, vulnerability scanning, compliance automation, and remediation at 10K–100K+ server scale.

### 1.1 Three-Layer Architecture

```
                   ┌──────────────────────────────────────┐
                   │     Frontend (Nuxt 4 + Vue 3)        │
                   │     Port 3000 — Web UI               │
                   │     Better Auth — Auth Provider      │
                   └──────────────┬───────────────────────┘
                                  │ REST /api/v1
                   ┌──────────────▼───────────────────────┐
                   │     Control Plane (FastAPI)           │
                   │     REST :8000 — API                  │
                   │     gRPC :50051 — Agent Comms (mTLS)  │
                   │     Metrics :9090 — Prometheus        │
                   └──────┬────────┴──────────┬───────────┘
                          │                   │
           ┌──────────────┼───────────────────┼───────────┐
           │              ▼                   ▼           │
           │  ┌──────────────┐  ┌──────────────────────┐  │
           │  │ PostgreSQL   │  │ Go Agent (per host)  │  │
           │  │ + TimescaleDB│  │ Static binary        │  │
           │  │ + pgBouncer  │  │ Outbound-only mTLS   │  │
           │  └──────┬───────┘  │ 60s heartbeat        │  │
           │  ┌──────┴───────┐  └──────────────────────┘  │
           │  │ Redis Cache  │                            │
           │  │ NATS Event   │  Compliance: Go hot path   │
           │  │ Bus          │  + FastAPI CRUD (hybrid)   │
           │  └──────────────┘                            │
           └──────────────────────────────────────────────┘
```

| Layer | Tech | Role |
|-------|------|------|
| **Control Plane** | FastAPI 0.138.1 (Python 3.11) | REST API, gRPC server, job orchestration, CVE processing, Ansible automation, compliance CRUD |
| **Linux Agent** | Go 1.24 (static binary, CGO_ENABLED=0) | Heartbeat, package inventory, vulnerability scan, job + playbook execution, 24 compliance collectors |
| **Frontend** | Nuxt 4.5.2 + Vue 3.5 + TypeScript | Dashboard, fleet management, Ansible automation UI, compliance dashboard, plugin marketplace, user admin |

### 1.2 Key Design Decisions

- **Agent outbound-only communication** — Agents never accept inbound connections. All communication originates from the agent via mTLS gRPC.
- **Event-driven core** — NATS JetStream as the async backbone. Background workers subscribe to topics for job results, policy changes, alerts, compliance events.
- **Hybrid compliance architecture** — Go microservice for CPU-bound hot path (ingest, drift detection, rule evaluation, scheduling); FastAPI for user-facing CRUD (inherits auth, audit, job engine).
- **JSON codec over gRPC proto** — Protobuf definitions exist at `proto/lokilinux.proto` but wire uses JSON encoding under the proto namespace for Go agent compatibility and debugging ease.
- **Two-service auth model** — Better Auth (embedded in Nuxt frontend) handles user authentication; the FastAPI backend validates bearer tokens against Better Auth's session endpoint via delegation.

---

## 2. Infrastructure Topology

### 2.1 Service Map

Nine services across five segmented Docker networks (`data-net`, `app-net`, `web-net` internal; `gateway-net` for host port publishing; `egress-net` for API outbound access), five named volumes for persistent data. There is no flat shared network anymore.

```
Service Dependency Chain:

postgres (TimescaleDB PG17, port 5432)
  └─ pgbouncer (v1.25.2, transaction pooling, port 6432)
       ├─ lokilinux-migrate (Alembic, one-shot migration)
       ├─ lokilinux-api (FastAPI, port 8000 REST + 9090 metrics)
       ├─ lokilinux-grpc (grpcio, port 50051 mTLS)
       └─ lokilinux-compliance (Go, port 8080 healthz + 9091 metrics)
            └─ lokilinux-frontend (Nuxt 4, port 3000 Web UI)

Independent infrastructure (no DB dependency):
  nats (NATS 2.10.29, port 4222 client + 8222 monitor)
  redis (Redis 7.4.9, port 6379, AOF + allkeys-lru)
```

### 2.2 Port Map

| Port | Service | Access | Protocol |
|------|---------|--------|----------|
| 3000 | `lokilinux-frontend` | Public | HTTP (Web UI) |
| 5432 | `postgres` | Internal | PostgreSQL |
| 6432 | `pgbouncer` | Internal | PostgreSQL (pooled) |
| 4222 | `nats` | Internal | NATS client |
| 8222 | `nats` | Internal | NATS monitoring |
| 6379 | `redis` | Internal | Redis |
| 8000 | `lokilinux-api` | Public | HTTP (REST API) |
| 9090 | `lokilinux-api` | Public | HTTP (Prometheus /metrics) |
| 50051 | `lokilinux-grpc` | Public (mTLS) | gRPC (agent heartbeat) |
| 8080 | `lokilinux-compliance` | Internal | HTTP (healthz) |
| 9091 | `lokilinux-compliance` | Internal | HTTP (Prometheus /metrics) |

### 2.3 Persistent Storage

| Volume | Mount | Used By |
|--------|-------|---------|
| `postgres_data` | `/var/lib/postgresql/data` | postgres |
| `nats_data` | `/data` | nats (JetStream) |
| `redis_data` | `/data` | redis |
| `plugins_dir` | `/opt/lokilinux/plugins` | lokilinux-grpc |
| `certs_dir` | `/etc/lokilinux/certs` | lokilinux-grpc, lokilinux-api, lokilinux-compliance |

### 2.4 Resource Limits (Production)

| Service | Memory | CPU |
|---------|--------|-----|
| postgres | 2G | 2 |
| pgbouncer | 256M | 0.5 |
| nats | 512M | 1 |
| redis | 512M | 1 |
| lokilinux-api | 1G | 2 |
| lokilinux-grpc | 1G | 2 |
| lokilinux-compliance | 512M | 1 |
| lokilinux-frontend | 512M | 1 |

### 2.5 Development Overrides

`docker-compose.dev.yml` provides hot-reload development:
- All infrastructure ports exposed to host (5432, 6432, 4222, 6222, 8222, 6379)
- Dev Dockerfiles with `uvicorn --reload` and `npm run dev`
- Bind-mounted source volumes (excluding `.venv`, `node_modules`)
- Relaxed resource limits (4G per service)
- Verbose PostgreSQL query logging

---

## 3. Control Plane — FastAPI Backend

The control plane is a three-tier event-driven FastAPI application at `backend/lokilinux/`.

### 3.1 Directory Layout

```
backend/lokilinux/
├── main.py              # App factory, lifespan, middleware, health endpoints
├── config.py            # Pydantic Settings (env-based configuration)
├── db.py                # SQLAlchemy async engine + session factory
├── settings_schema.py   # Flat KV platform settings (CRUD via PG upsert)
├── cache.py             # Redis cache-aside (domain-specific TTLs)
├── dependencies.py      # FastAPI dependency providers (db, cache, nats)
├── nats_topics.py       # Single source of truth for NATS subjects
├── grpc_server.py       # Standalone gRPC server bootstrap (mTLS)
│
├── api/
│   ├── v1/              # 16 REST router groups under /api/v1/
│   │   ├── routers/     # servers, jobs, cves, policies, alerts,
│   │   │                # playbooks, ansible-*, plugins, admin,
│   │   │                # dashboard, agent-install, categories
│   │   │                # (5 more)
│   │   │   └── compliance/  # 8 sub-routers (dashboard, baselines,
│   │   │                    # policy-engine, drift, file-integrity,
│   │   │                    # inventory, remediation, reports)
│   │   └── __init__.py  # Router aggregation (17 include_router calls)
│   └── grpc/            # gRPC service handlers
│       └── agent_service.py  # HeartbeatStream bidirectional handler
│
├── auth/                # Bearer token validation
│   ├── dependencies.py  # get_current_user, require_role
│   └── jwks_validator.py  # Better Auth session delegation
│
├── middleware/
│   └── rate_limit.py    # Redis-backed rate limiting (configurable)
│
├── models/              # 27 SQLAlchemy ORM models across 20 files
├── schemas/             # 16 Pydantic schema modules
├── services/            # 17 business logic service classes
└── workers/             # 13 background workers (NATS + asyncio loop)
```

### 3.2 REST API — Router Groups

| Router | Prefix | Purpose |
|--------|--------|---------|
| servers | `/api/v1/servers` | Fleet server CRUD, metrics, packages, vulnerabilities, maintenance mode |
| jobs | `/api/v1/jobs` | Job CRUD, scheduling, approval, cancellation, results |
| cves | `/api/v1/vulnerabilities` | CVE browser, severity summary, affected servers |
| policies | `/api/v1/policies` | Policy CRUD, run, audit trail |
| alerts | `/api/v1/alerts` | Alert list, acknowledge, resolve |
| playbooks | `/api/v1/playbooks` | Ansible playbook CRUD + execute |
| ansible-roles | `/api/v1/ansible-roles` | Ansible role CRUD with files dictionary |
| ansible-projects | `/api/v1/ansible-projects` | Ansible project CRUD |
| playbook-templates | `/api/v1/playbook-templates` | Job template CRUD + launch + history |
| plugins | `/api/v1/plugins` | Plugin marketplace (install/enable/disable) |
| agent-install | `/api/v1/agents` | Agent version/download, install instructions |
| dashboard | `/api/v1/dashboard` | Fleet summary, OS distribution, severity bars |
| admin | `/api/v1/admin` | Platform settings, user management |
| categories | `/api/v1/categories` | Server category CRUD |
| compliance | `/api/v1/compliance/*` | Compliance: baselines, policies, rules, drift, FIM, inventory, remediation, reports, dashboard |
| audit | `/api/v1/audit` | Audit log browsing |

All endpoints require JWT validation via `get_current_user` and optional role enforcement via `require_role()`.

### 3.3 Service Layer (17 Services)

| Service | File | Responsibility |
|---------|------|----------------|
| **AgentService** | `agent_service.py` | Heartbeat processing, package sync, vulnerability sync, health recording, job result application, compliance hash processing |
| **JobService** | `job_service.py` | Job creation (SHA256 dedup), approval, completion, status recomputation |
| **AlertService** | `alert_service.py` | Alert creation (PG upsert dedup), acknowledge, resolve, auto-resolve for agent-offline |
| **PolicyService** | `policy_service.py` | Target resolution, policy-driven job creation, cron next-run computation |
| **BaselineService** | `baseline_service.py` | DRAFT→PUBLISHED versioning, approval, content hashing, NATS publish |
| **RemediationService** | `remediation_service.py` | DRAFT→EXECUTING via JobService, plan creation with remediation actions |
| **ReportService** | `report_service.py` | Fleet summary data, XLSX/CSV/JSON/PDF generation |
| **CVEService** | `cve_service.py` | Agent vulnerability queries, NVD feed integration |
| **PluginService** | — | Install via job pipeline, enable/disable |
| **PlaybookService** | — | CRUD + execute with role snapshotting |
| **PlaybookTemplateService** | — | Template CRUD + launch + history |
| **AnsibleRoleService** | — | CRUD + file content snapshots |
| **AnsibleProjectService** | — | CRUD |
| **AuditService** | — | Audit log creation + paginated list |
| **ComplianceIngestService** | `compliance_ingest_service.py` | Domain hash diff, NATS publish for Go service |
| **ComplianceAsCodeImporter** | `complianceascode_importer.py` | XCCDF 1.2 datastream parsing, rule/policy-set upsert |

### 3.4 Background Workers (13 Workers)

**NATS Subscribers (6):**

| Worker | Topic | Action |
|--------|-------|--------|
| JobExecutorWorker | `JOB_RESULT` | `JobService.complete_job()` |
| PolicyWorker | `POLICY_CHANGED`, `POLICY_APPLY` | Cache invalidation + audit log |
| AlertProcessorWorker | `AGENT_UNHEALTHY` | `AlertService.create_alert()` |
| PluginWorker | `PLUGIN_INSTALL` | Cache invalidation |
| CVEProcessorWorker | `CVE_DATABASE_UPDATED` | Cache invalidation |
| NotificationWorker | `ALERT_CREATED` | SMTP/Slack delivery (via `asyncio.to_thread`) |

**Asyncio Loop Workers (7):**

| Worker | Interval | Action |
|--------|----------|--------|
| PolicySchedulerWorker | 30s tick | Atomic UPDATE claim, fires SCHEDULE-trigger policies |
| HeartbeatMonitorWorker | 60s sweep | Marks stale ACTIVE agents INACTIVE, publishes AGENT_UNHEALTHY |
| JobTimeoutWorker | 60s sweep | Marks stale QUEUED jobs TIMEOUT with dedup-free SQL |
| RetentionCleanupWorker | 3600s sweep | Deletes audit_logs past retention_days |
| RemediationSchedulerWorker | 30s tick | Dispatches APPROVED remediation plans whose maintenance window is open |
| RemediationVerificationWorker | 30s tick | Re-checks VERIFYING plans' actual state, closes the loop past exit-code-only success |
| CVEEnrichmentWorker | 10s tick | Fills CVSS/title/description/CWE from NVD, exploited/KEV date from CISA |

### 3.5 Database — 27 ORM Models

**Agent & Inventory:** Agent, AgentHealth (hypertable), AgentMetrics (hypertable)  
**Jobs:** Job, JobResult  
**Security:** Alert, AlertRule  
**Vulnerabilities:** CVE, Package, PackageVulnerability, AgentVulnerability  
**Policies:** Policy, PolicyAudit  
**Compliance:** ComplianceRule, RemediationTemplate, PolicySet, PolicySetRule, PolicyAssignment, Baseline, BaselineVersion, BaselineApproval, BaselineEffective, DriftEvent (hypertable), DriftDetail (hypertable), FileHash, FileChange (hypertable), InventoryBlob, InventorySnapshot (hypertable), InventoryDelta (hypertable), RuleEvaluation (hypertable), ComplianceScore (hypertable), ComplianceReport  
**Automation:** Playbook, AnsibleRole, AnsibleProject, PlaybookTemplate  
**Platform:** Category, Project, Plugin, PluginInstallation  
**Auth/Audit:** AuditLog, UserProfile, Setting

TimescaleDB hypertables used for: metrics, rule_evaluations, drift events, inventory snapshots/deltas, file changes, compliance scores.

### 3.6 Configuration

Pydantic `Settings` model reads from environment variables. Key groups:

| Group | Variables | 
|-------|-----------|
| Database | `DATABASE_URL`, `POSTGRES_*`, `PGBOUNCER_*` |
| Cache | `REDIS_URL`, `REDIS_PASSWORD` |
| Message Bus | `NATS_URL` |
| Auth | `BETTER_AUTH_URL`, `BETTER_AUTH_SECRET` |
| gRPC | `GRPC_PORT`, `AGENT_CERT_DIR`, `CA_*`, `SERVER_*` |
| Agent | `AGENT_VERSION`, `AGENT_HEARTBEAT_INTERVAL`, `AGENT_MAX_OFFLINE_DAYS` |
| Frontend | `FRONTEND_URL` |
| CVE | `CVE_FEED_UPDATE_INTERVAL`, `NVD_API_KEY` |
| Notifications | `SMTP_*`, `SLACK_*` |

Flat KV platform settings via `settings_schema.py` (PG upsert, groups: security, fleet, notifications, retention, CVE, branding, plugins, repo).

---

## 4. Linux Agent — Go Daemon

A static Go 1.24 binary deployed on every managed host. All mutating operations use `systemd-run` to escape the agent's own systemd sandbox.

### 4.1 Directory Layout

```
agent/
├── cmd/agent/main.go           # Entry point: config, manager, signal handling
├── internal/
│   ├── agent/
│   │   ├── manager.go          # Heartbeat loop, job dispatch, compliance runner
│   │   └── logbuffer.go        # LogRingBuffer (100 lines for heartbeats)
│   ├── communication/
│   │   ├── grpc_client.go      # mTLS gRPC client, JSON codec, reconnect logic
│   │   └── heartbeat_manager.go  # Typed streaming loop (alternative path)
│   ├── config/
│   │   └── config.go           # YAML config (/etc/lokilinux/agent.yaml)
│   ├── storage/
│   │   └── sqlite.go           # Pure-Go SQLite (no CGO): jobs, packages, config, compliance
│   ├── modules/
│   │   ├── system_info.go      # OS snapshot (/proc, /etc, lsblk, network)
│   │   ├── package_manager.go  # Distro detection, dpkg/rpm, update check, CVE lookup
│   │   ├── package_updater.go  # Package upgrade via systemd-run
│   │   ├── job_executor.go     # Shell command via systemd-run
│   │   ├── ansible_executor.go # Ansible playbook runner
│   │   ├── plugin_installer.go # HTTP download + SHA256 verify + atomic rename
│   │   ├── metrics.go          # CPU%/mem/disk via /proc delta
│   │   ├── vulnerability.go    # CVE data struct (dnf/yum only)
│   │   └── systemd_run.go      # systemd-run escape hatch for sandboxed operations
│   └── compliance/
│       ├── collector.go        # Collector interface + registry
│       ├── runner.go           # Configurable tick cadence, state persistence
│       ├── canonical.go        # BLAKE3 + deterministic JSON hashing
│       └── [24 collector files]# sshd, sysctl, users, mounts, sudo, pam, auditd,
│                                # firewall, selinux, kernel, login_defs, password_policy,
│                                # cron, systemd_services, network, time_sync,
│                                # kernel_modules, open_ports, processes, capabilities,
│                                # certificates, repositories, container_runtime,
│                                # file_integrity
├── gen/
│   ├── lokilinux/              # Hand-written proto structs + JSON tags (runtime types)
│   └── proto/                  # protoc-generated code (schema definition only)
├── .nfpm.yaml                  # .deb/.rpm packaging config
└── go.mod                      # Dependencies: grpc, yaml.v3, blake3, sqlite
```

### 4.2 Manager Loop

The `Manager` runs the central heartbeat loop:

```
Timer tick → Collect system info → Build heartbeat payload →
  GRPCClient.SendHeartbeat() → Handle response →
    Dispatch pending jobs → Accumulate results → Next heartbeat
```

Key behaviors:
- **Heartbeat interval**: 60s default, configurable via agent.yaml
- **Exponential backoff**: After 3 consecutive failures, 2x per failure (capped at 5 min)
- **Forced reconnect**: After 3 consecutive failures, tears down gRPC connection and dials fresh (fixes grpc-go EOF wedge after server restart)
- **In-flight job guard**: Prevents duplicate dispatch of the same `job_id`
- **SQLite purge**: Background goroutine purges old records every 24 hours
- **Log ring buffer**: Last 100 log lines + severity counts attached to each heartbeat

### 4.3 Agent Modules

| Module | Collection Interval | Data Source | Purpose |
|--------|-------------------|-------------|---------|
| **SystemInfo** | Every heartbeat | /proc, /etc, /sys, lsblk | OS facts, disks, network interfaces, listening ports, system users |
| **PackageManager** | Every heartbeat (1h rate-limit on updates) | dpkg/rpm, dnf/apt/zypper | Installed packages, available updates, SHA256 checksum for delta |
| **PackageUpdater** | On demand (job) | systemd-run | Package install/upgrade/remove via native package manager |
| **JobExecutor** | On demand (job) | systemd-run | Arbitrary shell commands with output capture |
| **AnsibleExecutor** | On demand (job) | ansible-playbook (local) | Playbook execution on localhost with role materialization |
| **PluginInstaller** | On demand (job) | HTTP download | Plugin artifact download, SHA256 verify, atomic install |
| **Metrics** | 5 min | /proc/stat, /proc/meminfo, statfs | CPU%, memory, disk usage, load average |
| **Vulnerability** | On heartbeat | dnf updateinfo / apt | CVE ID + severity + fix version (dnf/yum only) |

### 4.4 Compliance Collectors (24 Built-in)

Compiled-in collectors, not dynamically loaded plugins. Each implements `Collector` interface: `Domain()`, `Collect(ctx)`, `Interval()`.

| Collector | Domain | Interval | Data Source |
|-----------|--------|----------|-------------|
| SSHDCollector | sshd | Heartbeat | `sshd -T` |
| SysctlCollector | sysctl | — | sysctl output |
| UsersCollector | users | Heartbeat | /etc/passwd (UID≥1000) |
| MountsCollector | mounts | — | /proc/mounts |
| SudoCollector | sudo | — | /etc/sudoers |
| PAMCollector | pam | — | PAM config files |
| AuditdCollector | auditd | — | auditd rules |
| FirewallCollector | firewall | — | iptables/nftables |
| SELinuxCollector | selinux | — | getenforce/sestatus |
| KernelCollector | kernel | — | /proc/sys/kernel |
| LoginDefsCollector | login_defs | — | /etc/login.defs |
| PasswordPolicyCollector | password_policy | — | PAM passwdqc configs |
| CronCollector | cron | — | Crontabs |
| SystemdServicesCollector | systemd_services | — | systemctl list-units |
| NetworkCollector | network | — | /sys/class/net |
| TimeSyncCollector | time_sync | — | timedatectl/chronyc |
| KernelModulesCollector | kernel_modules | — | lsmod |
| OpenPortsCollector | open_ports | — | /proc/net |
| ProcessesCollector | processes | Heartbeat | /proc/* (cmdlines hashed) |
| CapabilitiesCollector | capabilities | — | getcap walk |
| CertificatesCollector | certificates | — | Certificate file scan |
| RepositoriesCollector | repositories | — | Repo configs |
| ContainerRuntimeCollector | container_runtime | — | docker/podman socket |
| FileIntegrityCollector | file_integrity | 15 min | BLAKE3 walk of /etc, /boot, /usr/lib/systemd |

### 4.5 Sandbox Architecture

All host-mutating jobs (package updates, Ansible, shell commands) run via transient `systemd-run` units to bypass the agent's own `ProtectSystem=strict` and `PrivateTmp` hardening:

```
Agent (systemd unit, ProtectSystem=strict, PrivateTmp=yes)
  └─ systemd-run --wait --quiet --collect --unit=lokilinux-job-<id> \
       --property=RuntimeMaxSec=<timeout> \
       -- <command>
          └─ Transient systemd unit (no sandbox restrictions)
               └─ stdout/stderr → /var/lib/lokilinux/job-output/<jobID>.{stdout,stderr}
```

File-based I/O (not `--pipe`) avoids a Go D-Bus fd-passing bug. Systemd's `RuntimeMaxSec` provides timeout enforcement that survives client disconnection.

### 4.6 Compliance Delta Sync

Compliance collectors use content-addressed hashing (BLAKE3 of canonical JSON):
- `Hashes()` — cheap, sent every heartbeat (domain → BLAKE3 map, ~200 bytes for 24 domains)
- `FullBody()` — expensive, sent only for domains the server flags via `resync_domains` in heartbeat response
- State persisted to local SQLite for restart resilience

### 4.7 Agent Configuration

File: `/etc/lokilinux/agent.yaml`

```yaml
platform:
  url: "https://platform.example.com:443"
  grpc_endpoint: "grpc.example.com:50051"

identity:
  agent_id: "uuid-string"
  cert_file: "/etc/lokilinux/certs/agent.crt"
  key_file: "/etc/lokilinux/certs/agent.key"
  ca_file: "/etc/lokilinux/certs/ca.crt"

heartbeat:
  interval_sec: 60
  timeout_sec: 30
  backoff:
    initial_sec: 5
    max_sec: 300
    factor: 2

cache:
  sqlite_db: "/var/lib/lokilinux/agent.db"
  retention_days: 30

job_execution:
  max_parallel: 5
  timeout_sec: 3600
  sandbox: true
```

### 4.8 Build & Packaging

| Target | Output |
|--------|--------|
| `make agent-build` | Static binary `agent/agent` (linux/amd64, CGO_ENABLED=0) |
| `make agent-build-arm64` | Static binary (linux/arm64) |
| `make agent-package` | `.tar.gz` + `.deb` + `.rpm` for both arches via nfpm |

Post-install: binary at `/usr/local/bin/lokilinux-agent`, creates `/etc/lokilinux/` and `/var/lib/lokilinux/`, systemd unit installed, enrollment instructions printed.

---

## 5. Frontend — Nuxt 4 + Vue 3

A single-page application with server-side rendering, using Nuxt 4.5.2, Vue 3.5, TypeScript, Pinia, Tailwind CSS 4, and Better Auth.

### 5.1 Architecture

```
BROWSER
  │
  ├─ app.vue → layouts/{default,auth}.vue → pages/*
  │    ├─ components/{ui,dashboard,server,…}/*.vue (Radix Vue primitives)
  │    ├─ composables/{useAuth,useServers,useJobs,useToast,useBranding}
  │    ├─ stores/{servers,jobs,cve,plugins,policies,compliance,…} (Pinia)
  │    ├─ utils/{api,cn,formatBytes,websocket,agentPackages}
  │    └─ middleware/auth.global.ts (SPA route guard)
  │
  └─ NITRO SERVER (SSR on Node 22)
       ├─ server/utils/auth.ts      Better Auth + Kysely + Postgres
       ├─ server/utils/session.ts   getSession / requireSession
       ├─ server/middleware/auth.ts  Server-side session check
       └─ server/api/auth/[...all].ts  Better Auth handler
            │
            └─ Proxy: /api/v1/** → http://lokilinux-api:8000 (FastAPI)
```

### 5.2 Pages (File-based Routing, ~35 routes)

| Route | Component | Purpose |
|-------|-----------|---------|
| `/` | `index.vue` | Dashboard: stat cards, OS donut, severity bars, activity feed |
| `/servers` | `servers/index.vue` | Server list with inline category/project assignment |
| `/servers/:id` | `servers/[id].vue` | 8-tab server detail (Overview, Hardware, Packages, Vulns, Jobs, Users, Logs, Settings) |
| `/agents` | `agents/index.vue` | Agent version table, install instructions, download cards |
| `/jobs` | `jobs/index.vue` | Job list with cursor pagination, create/cancel/approve |
| `/alerts` | `alerts/index.vue` | Alert list with acknowledge/resolve |
| `/vulnerabilities` | `vulnerabilities/index.vue` | CVE browser with severity filter |
| `/policies` | `policies/index.vue` | Policy list + PolicyWizard dialog |
| `/policies/:id` | `policies/[id].vue` | Policy detail, edit, audit trail |
| `/plugins` | `plugins/index.vue` | Plugin marketplace with install/enable/disable |
| `/compliance` | `compliance/index.vue` | Compliance dashboard |
| `/compliance/baselines` | `compliance/baselines/index.vue` | Baseline list + create |
| `/compliance/baselines/:id` | `compliance/baselines/[id].vue` | Baseline detail, version lifecycle |
| `/compliance/policies` | `compliance/policies/index.vue` | Policy set list + import |
| `/compliance/policies/:id` | `compliance/policies/[id].vue` | Policy set detail, coverage |
| `/compliance/rules` | `compliance/rules/index.vue` | Rule catalog with CEL expression viewer |
| `/compliance/drift` | `compliance/drift/index.vue` | Drift event list |
| `/compliance/drift/:id` | `compliance/drift/[id].vue` | Drift detail with diff viewer |
| `/compliance/remediation` | `compliance/remediation/index.vue` | Remediation plan list |
| `/compliance/remediation/:id` | `compliance/remediation/[id].vue` | Plan detail with submit/approve |
| `/compliance/file-integrity` | `compliance/file-integrity/index.vue` | File hashes + changes timeline |
| `/compliance/reports` | `compliance/reports/index.vue` | Report creation + download |
| `/automation/ansible/playbooks` | `automation/ansible/playbooks/index.vue` | Playbook list |
| `/automation/ansible/playbooks/:id` | `automation/ansible/playbooks/[id].vue` | Playbook detail + YAML editor |
| `/automation/ansible/roles` | `automation/ansible/roles/index.vue` | Role list |
| `/automation/ansible/roles/:id` | `automation/ansible/roles/[id].vue` | Role detail + files |
| `/automation/ansible/projects` | `automation/ansible/projects/index.vue` | Project list |
| `/automation/ansible/templates` | `automation/ansible/templates/index.vue` | Job template list + launch |
| `/auth/login` | `auth/login.vue` | Login page |
| `/account/security` | `account/security.vue` | Password change, 2FA enrollment |
| `/admin/settings` | `admin/settings.vue` | Platform settings (8 groups) |
| `/admin/users` | `admin/users/index.vue` | User management |
| `/admin/audit` | `admin/audit.vue` | Audit log browser |

### 5.3 UI Components

Custom implementation (Radix Vue primitives + Tailwind CSS 4):
- **Layout**: `DataTable`, `Button`, `Dialog`, `Select`, `Input`, `Badge`, `Card`, `Checkbox`, `Switch`, `MultiSelect`, `FormField`, `Stepper`, `AppTabs`, `Sheet`, `Alert`, `Textarea`, `Label`, `Skeleton`, `Avatar`, `Separator`, `Table` (structural)
- **Dashboard**: `StatCard`, `SeverityBarList`, `OsDistributionDonut`, `RecentActivityFeed`
- **Server**: `MetricsCards` (CPU/RAM/Disk/Swap with threshold coloring)
- **Feature**: `PolicyWizard`, `JobDetail`, `PlaybookEditor`, `UserSettingsModal`, `ColorModeButton`

### 5.4 State Management (Pinia Stores)

| Store | State | Key Actions |
|-------|-------|-------------|
| servers | servers[], categories[], projects[], metrics | fetchServers (cursor), toggleMaintenance, assignServer |
| jobs | jobs[], filters | fetchJobs (cursor), createJob, cancelJob, approveJob |
| cve | cves[], summary (severity counts) | fetchCves (cursor) |
| plugins | plugins[] | fetchPlugins, installPlugin, enablePlugin, disablePlugin |
| policies | policies[], audit | fetchPolicies, runPolicy, toggleEnabled |
| playbooks | playbooks[] | fetchPlaybooks, executePlaybook |
| ansible_roles | roles[] | CRUD |
| ansible_projects | projects[] | CRUD |
| playbook_templates | templates[] | fetchTemplates, launchTemplate |
| compliance | baselines, rules, drift, remediation, reports, FIM | ~20 actions (dashboard, CRUD per sub-domain) |

### 5.5 Authentication Flow

1. **Client startup**: `plugins/auth.client.ts` calls `refreshAuthToken()`
2. **SPA navigation**: `middleware/auth.global.ts` checks `useAuth().data`, redirects to `/auth/login` if unauthenticated, enforces 2FA redirect
3. **API calls**: `useApi()` attaches Bearer token from `auth:token` state; on 401, redirects to `/auth/login`
4. **SSR**: Nuxt server middleware checks session via `requireSession()`, redirects on 401
5. **Better Auth handler**: `server/api/auth/[...all].ts` → `auth.handler()` for login, signup, session, 2FA, admin APIs

### 5.6 Key Dependencies

| Package | Purpose |
|---------|---------|
| `nuxt` 4.5.2 | Framework |
| `vue` 3.5 | UI library |
| `pinia` 3 | State management |
| `better-auth` 1.6 | Authentication (+ username, twoFactor, bearer, admin plugins) |
| `tailwindcss` 4 | CSS framework |
| `@radix-icons/vue` | Icons (Lucide-based) |
| `codemirror` + `@codemirror/lang-yaml` | YAML editor |
| `vue-sonner` | Toast notifications |
| `class-variance-authority` + `tailwind-merge` | Component variants |
| `@vueuse/core` | Composition utilities |

---

## 6. Compliance & Drift Management

A hybrid module: Go microservice for CPU-bound hot path, FastAPI for user-facing CRUD, with NATS JetStream as the glue.

### 6.1 Architecture — Hybrid Topology

```
Go Agent (fleet host)
  │ mTLS gRPC :50051
  ▼
lokilinux-grpc (FastAPI, existing)
  │ NATS JetStream publish per-domain snapshot
  ▼
lokilinux-compliance (NEW Go microservice)
  ├─ Ingest consumer → BLAKE3 canonicalize → PG upsert
  ├─ Baseline resolver → scope-tree merge → effective baseline
  ├─ CEL rule evaluator → PASS/FAIL per rule
  ├─ Drift detector → 3-way comparison → severity
  └─ Scheduler → leader-elected periodic dispatch
      │
      │ NATS publish results
      ▼
lokilinux-api (FastAPI, existing)
  ├─ REST /api/v1/compliance/* → UI reads from PG
  └─ JobService → pending_jobs on next heartbeat → Agent
```

The Go service (`lokilinux-compliance`) is stateless, scalable via NATS JetStream queue groups. Exposes only `/healthz` (Fiber) and `/metrics` (Prometheus). Never touches Better Auth, Redis, or the job dispatch path directly.

### 6.2 Go Microservice Packages

| Package | Purpose |
|---------|---------|
| `internal/config` | YAML + env config, defaults |
| `internal/ingest` | JetStream pull consumer, canonicalize + BLAKE3, upsert inventory_blobs/snapshots, delta computation |
| `internal/baseline` | Scope-tree merge (7-level specificity: GLOBAL < OS < ROLE < ENVIRONMENT < DATACENTER < CLUSTER < APPLICATION), deepMergeOverwrite, BLAKE3 hashing, Ed25519 signing |
| `internal/rules` | CEL evaluator with compiled program cache per rule.ID, 6-value Result enum |
| `internal/drift` | 3-way comparison (baseline vs current vs previous), JSON-pointer field diffs, severity-by-domain |
| `internal/scoring` | Domain-to-category mapping (5 buckets: security, configuration, filesystem, kernel) |
| `internal/scheduler` | NATS KV leader election, periodic SCHEDULED→QUEUED dispatch |
| `internal/storage` | pgx pool, hand-written SQL (not sqlc) for all persistence |
| `internal/telemetry` | Prometheus counters (SnapshotsIngestedTotal, DriftEventsTotal) |

### 6.3 Compliance REST API Sub-routers (under /api/v1/compliance/)

| Router | Endpoints |
|--------|-----------|
| dashboard | `GET /dashboard/top-violations`, `GET /dashboard/top-changed-files` |
| baselines | CRUD + `POST /{id}/versions/{vid}/{submit,approve,publish,rollback}`, `GET /effective/{agent_id}` |
| policy-engine | `GET /rules[/{id}]`, `GET /rules/{id}/coverage`, `GET /policy-sets`, `POST /policy-sets/import`, CRUD policy-set rules, CRUD policy-assignments |
| drift | `GET /events`, `GET /events/{id}/details` |
| file-integrity | `GET /files`, `GET /changes` |
| inventory | `GET /snapshots`, `GET /deltas` |
| remediation | CRUD plans + `POST /{id}/{submit,approve}` |
| reports | `POST /create`, `GET /{id}`, `GET /{id}/download` (JSON/CSV/XLSX/PDF) |

### 6.4 Compliance Domain Structure

14 specification documents under `docs/compliance/`:

| Document | Focus |
|----------|-------|
| `00-OVERVIEW.md` | Architecture overview, 10 design decisions (D1–D9), hybrid topology |
| `01-DATA-MODEL.md` | Full PostgreSQL schema (25+ tables) |
| `02-GO-SERVICE.md` | Go microservice architecture |
| `03-AGENT-PLUGIN-SDK.md` | Compiled-in collector design |
| `04-PROTOCOL.md` | Wire protocol, delta sync, 25 NATS subjects |
| `05-API.md` | 40+ REST endpoints |
| `06-BASELINE.md` | Scope tree, versioning, signing, approval workflow |
| `07-POLICY-ENGINE.md` | ComplianceAsCode import, CEL evaluation |
| `08-DRIFT-FIM.md` | 3-way comparison, diff algorithm, severity |
| `09-REMEDIATION.md` | Remediation workflow, 4 execution providers |
| `10-AI.md` | AI compliance assistant (Anthropic/OpenAI/Ollama) |
| `11-FRONTEND.md` | 12 Nuxt 4 pages, Pinia stores |
| `12-DIAGRAMS.md` | 8 Mermaid workflow/sequence diagrams |
| `13-OPS.md` | 100K-fleet scaling, security, 5-phase roadmap |

---

## 7. Communication Protocols

### 7.1 gRPC — Agent ↔ Control Plane

**Transport**: mTLS (TLS 1.3) over TCP :50051, outbound-only from agents

**Services** (defined in `proto/lokilinux.proto`):

```
service AgentService {
  rpc HeartbeatStream(stream AgentHeartbeatRequest)
      returns (stream AgentHeartbeatResponse);  // bidirectional
  rpc ReportMetrics(stream MetricsData)
      returns (MetricsAck);                      // client-streaming
  rpc SyncPolicy(PolicySyncRequest)
      returns (PolicyConfig);                    // unary
}
```

**Wire reality**: Although protobuf definitions exist, the actual wire uses JSON codec registered under the proto namespace. Both Go agent and Python server encode/decode JSON against hand-written structs (not generated protobuf code). This avoids binary protobuf overhead while keeping gRPC method names.

### 7.2 Heartbeat Protocol

**Request (agent → server) — every 60s:**

| Field | Source | Content |
|-------|--------|---------|
| `agent_id`, `timestamp` | Manager | Identity and time |
| `system_status` | SystemInfoModule | OS, kernel, CPU, memory, disks, network, ports, users |
| `packages` | PackageManagerModule | Installed packages list |
| `packages_checksum` | PackageManagerModule | SHA256 of sorted packages (delta sync) |
| `vulnerabilities` | VulnerabilityModule | CVE matches (dnf/yum only) |
| `health` | SystemInfoModule | CPU%, memory%, disk%, swap% |
| `domain_hashes` | ComplianceRunner | Per-domain BLAKE3 hash map (~200 bytes) |
| `domain_full` | ComplianceRunner | Full compliance facts (only for resync domains) |
| `job_results` | Manager | Completed/failed job outputs |
| `recent_logs` | LogRingBuffer | Last 100 log lines + severity counts |
| `agent_version` | Version constant | Build-time version string |

**Response (server → agent):**

| Field | Source | Content |
|-------|--------|---------|
| `pending_jobs` | JobService | Jobs to execute (typed by job_type) |
| `resync_domains` | ComplianceIngestService | Domains needing full body resync |
| `policy` | PolicyService | Policy updates |
| `plugin_actions` | PluginService | Plugin install/update/remove commands |
| `next_heartbeat_interval` | AgentService | Override default 60s interval |

### 7.3 NATS Event Bus

All subjects under `lokilinux.` prefix. Key topics:

| Subject | Publisher | Subscriber | Payload |
|---------|-----------|------------|---------|
| `lokilinux.job.created` | API | — | Job metadata |
| `lokilinux.job.result` | gRPC (agent relay) | JobExecutorWorker | JobResult |
| `lokilinux.policy.changed` | API | PolicyWorker | Policy ID + diff |
| `lokilinux.policy.apply` | API | (dead — no subscriber) | Policy target + action |
| `lokilinux.alert.created` | Workers | NotificationWorker | Alert payload |
| `lokilinux.agent.unhealthy` | HeartbeatMonitor | AlertProcessorWorker | Agent ID + reason |
| `lokilinux.cve.database.updated` | CVE fetcher | CVEProcessorWorker | CVE DB version |
| `lokilinux.plugin.install` | API | PluginWorker | Plugin spec |
| `lokilinux.compliance.snapshot.<domain>` | gRPC (agent relay) | Compliance ingest | BLAKE3 + inventory facts |
| `lokilinux.compliance.baseline.published` | API (BaselineService) | Compliance baseline consumer | Baseline version ID |
| `lokilinux.compliance.drift.detected` | Compliance service | — | DriftEvent |
| `lokilinux.compliance.score.updated` | Compliance service | — | ComplianceScore |
| `lokilinux.compliance.drift.resolved` | API | — | Drift ID |

### 7.4 REST API — Frontend ↔ Backend

- **Base**: `/api/v1/*`
- **Proxy**: Nuxt Nitro server proxies `/api/v1/**` → `http://lokilinux-api:8000` (internal)
- **Auth**: Bearer token (JWT from Better Auth) in `Authorization` header
- **Pagination**: Cursor-based (`CursorPage` generic with `encode_cursor`/`decode_cursor`)
- **Serialization**: ORJSON (orjson) for performance

### 7.5 WebSocket

Client-side composable `useWebSocket()` provides real-time events:
- `job:log` — Job stdout/stderr streaming
- `agent:status` — Agent online/offline transitions
- `alert` — New alert notifications
- `metrics` — Live metric updates

Exponential-backoff reconnection, typed event emitter.

---

## 8. Authentication & Authorization

### 8.1 Two-Service Auth Model

```
FRONTEND (Better Auth)                  BACKEND (Token Delegation)
                           
User → Login → Better Auth  ←─── JWT ───→ FastAPI validate via
        session cookie                       GET /api/auth/get-session
        + Bearer token                       (Redis-cached, 60s TTL)
```

### 8.2 Authentication Flow

1. **User logs in** at `/auth/login` via Better Auth `signIn.email()`
2. **Better Auth issues**: session cookie (SSR) + Bearer token (SPA)
3. **SPA stores token** in `auth:token` Pinia state
4. **API calls** via `useApi()` attach Bearer token automatically
5. **FastAPI validates** by calling `GET /api/auth/get-session` on the frontend
6. **Redis cache**: session tokens cached for 60s; circuit breaker (2 failures → 5s negative cache if auth server is down)
7. **On 401**: frontend redirects to `/auth/login`

### 8.3 Role-Based Access Control

**Roles**: `ADMIN`, `MANAGER`, `OPERATOR`, `VIEWER`, `AUDITOR`

Enforced via `require_role()` FastAPI dependency:
- `ADMIN` bypasses all role checks
- `VIEWER` — read-only access
- `AUDITOR` — audit log + compliance reports
- `MANAGER` — operational actions (jobs, policies)
- `OPERATOR` — day-to-day fleet management

**Two-Factor Authentication**: Optional TOTP-based 2FA via Better Auth `twoFactor` plugin.

### 8.4 Agent Authentication (mTLS)

- Self-signed CA generates RSA 4096 certificates
- Each agent receives a unique certificate at enrollment
- Server validates agent certs; agents validate server cert
- Cert validity: 365 days (agent), auto-renewal with 30-day window

**Enrollment flow**:
1. Install script runs on target host
2. Script calls REST API with enrollment token (one-time, Redis-backed)
3. Server generates agent certificate signed by CA
4. Agent installs cert + key + CA chain
5. Agent starts heartbeat with mTLS gRPC

---

## 9. Data Flow — End to End

### 9.1 Agent Heartbeat + Job Dispatch

```
Agent (60s tick)
  │
  ├── Collect system info (OS, packages, vulns, health)
  ├── Collect compliance hashes (24 domains, BLAKE3)
  ├── Collect completed job results
  ├── Build heartbeat payload
  │
  └── mTLS gRPC → lokilinux-grpc (HeartbeatStream)
       │
       ▼ lokilinux-api (via NATS + DB)
       │
       ├── AgentService.update_heartbeat()
       │   ├── Upsert agent + packages (delta via SHA256 checksum)
       │   ├── Upsert vulnerabilities
       │   ├── Record health metrics
       │   ├── Apply completed job results
       │   ├── Publish compliance domain hashes → NATS (for Go service)
       │   └── Return pending_jobs + resync_domains
       │
       └── Response → Agent
            │
            └── Dispatch jobs (parallel goroutines)
                ├── PACKAGE_UPDATE → systemd-run → package manager
                ├── ANSIBLE_PLAYBOOK → systemd-run → ansible-playbook
                ├── PLUGIN_INSTALL → HTTP download + SHA256 verify
                └── CUSTOM_COMMAND → systemd-run → shell command
                     │
                     └── Result → pendingResults → next heartbeat
```

### 9.2 Compliance Scan Cycle

```
Agent                                       Compliance Service (Go)
  │                                                    │
  ├── Runner ticks collectors (1-min cadence)          │
  ├── BLAKE3 hash per domain                           │
  └── Hashes → heartbeat ────── NATS ────► Ingest consumer
                                               │
                    ┌───────────────────────────┤
                    │                           │
                    ▼                           ▼
            Upsert inventory_blob       Compute inventory_delta
            (canonical JSON + hash)      (diff from previous snapshot)
                    │                           │
                    ▼                           ▼
            Publish snapshot_domain →     RuleEvaluator (CEL)
            BaselineResolver merge             │
                    │                          ▼
                    ▼                   PASS/FAIL → RuleEvaluation
            Effective baseline          (hypertable)
                    │                          │
                    └──────────┬──────────────┘
                               ▼
                       DriftDetector
                       (3-way comparison)
                         │
                         ▼
                   DriftEvent (hypertable)
                   + ComplianceScore update
```

### 9.3 Remediation Workflow

```
Operator creates RemediationPlan
  → DRAFT
  → Add RemediationActions (rule+drift references)
  → Submit → IN_REVIEW
  → Approve → APPROVED
  → Execute → JobService.create_job() per action
       │
       ▼
  Job → pending_jobs → next agent heartbeat
       │
       ▼
  Agent executes → JobResult → lokilinux.job.result NATS topic
       │
       ▼
  JobExecutorWorker → JobService.complete_job()
       │
       ▼
  RemediationService → update plan status
  → COMPLETED (or ROLLED_BACK on failure)
```

### 9.4 Baseline Version Lifecycle

```
DRAFT (editable content)
  │ Submit
  ▼
SUBMITTED (locked content, awaiting approval)
  │ Approve (sign with Ed25519)
  ▼
APPROVED (signed, ready to publish)
  │ Publish
  ▼
PUBLISHED (active, sent via NATS to compliance service)
  │ (optional) Rollback
  ▼
ROLLED_BACK (superseded, previous version re-activated)

Version hashing: BLAKE3 of canonical JSON for content integrity tracking.
Scope: GLOBAL < OS < ROLE < ENVIRONMENT < DATACENTER < CLUSTER < APPLICATION
  (most-specific key wins in deep merge)
```

---

## 10. Deployment & Operations

### 10.1 Makefile Targets

| Target | Action |
|--------|--------|
| `make up` | Start production stack (detached) |
| `make down` | Stop all containers |
| `make build` | Build all Docker images |
| `make dev` | Start dev stack (hot-reload, ports exposed) |
| `make init` | Full first-run (certs + volumes + build + migrate + admin user) |
| `make certs` | Generate CA + server mTLS certificates |
| `make proto` | Regenerate Go + Python protobuf |
| `make agent-build` | Static Go binary linux/amd64 |
| `make agent-build-arm64` | Static Go binary linux/arm64 |
| `make agent-package` | Both arches → .tar.gz + .deb + .rpm |
| `make agent-test` | Go tests with -race -cover |
| `make compliance-build` | Static compliance binary linux/amd64 |
| `make compliance-test` | Compliance Go tests with -race -cover |
| `make scan-image` | Trivy scan of all lokilinux/* images, fails on HIGH/CRITICAL |
| `make sbom IMAGE=<img>` | CycloneDX SBOM for one image into `sbom/` |
| `make logs` | Tail all service logs |
| `make ps` | Show container status |

### 10.2 Dockerfiles

| Component | Base Image | Final Image | Strategy |
|-----------|-----------|-------------|----------|
| Backend | python:3.11.15-slim | python:3.11.15-slim (multi-stage venv, non-root `appuser` uid 10001, no curl/pip/setuptools/libpq5) | Multi-stage, pip installs in builder, Python-stdlib healthcheck |
| Frontend | node:22.23.1-alpine | node:22.23.1-alpine (non-root user) | Multi-stage, `npm ci` + nuxt build |
| Compliance | golang:1.26 | gcr.io/distroless/static-debian12 (`USER nonroot:nonroot`) | Multi-stage, no shell |
| Agent | — | Static binary + nfpm .deb/.rpm | CGO_ENABLED=0 cross-compile |

Runtime images are pinned to `${LOKILINUX_VERSION}` (currently `0.3.0`) — never `latest`. Vulnerability scanning gate: `make scan-image` (Trivy, fails on HIGH/CRITICAL); SBOMs via `make sbom IMAGE=...`; enforced in CI by `.github/workflows/security-pipeline.yml`.

### 10.3 Agent Installation (Remote Hosts)

Curl-installable script `scripts/install-agent.sh`:
1. Detect OS/architecture
2. Download agent binary from platform using enrollment token
3. POST to REST API to register agent and obtain certificate
4. Install mTLS certificate + key + CA chain
5. Write `/etc/lokilinux/agent.yaml`
6. Install systemd unit
7. Start and enable `lokilinux-agent` service

### 10.4 First-Run Initialization

`scripts/docker-init.sh`:
1. Verify `.env` exists
2. Generate certificates (if missing)
3. Create runtime directories + Docker volumes (cert keys chowned to uid 10001 so non-root services can read them)
4. Build all Docker images
5. Start infrastructure (postgres, pgbouncer, nats, redis)
6. Wait for PostgreSQL readiness
7. Start app services (api, grpc, frontend, migrate)
8. Run Alembic migrations
9. Run Better Auth migrations
10. Create admin user (password printed at end)

API readiness is polled with a Python `urllib` one-liner via `docker compose exec` — the runtime image ships no curl.

### 10.5 Logging

- **Backend**: structlog structured JSON logging
- **Agent**: `slog` with 100-entry ring buffer per agent (attached to heartbeats)
- **Frontend**: Nuxt/Nitro server logs, client-side console
- **Workers**: Structured logs via Python logging
- **Level**: Configurable per service via `LOG_LEVEL` env var

### 10.6 Monitoring

| Service | Endpoint | Metrics |
|---------|----------|---------|
| lokilinux-api | `/health` (8000), `/metrics` (9090) | App health, request counts |
| lokilinux-grpc | gRPC health check | Connection count, heartbeat rate |
| lokilinux-compliance | `/healthz` (8080), `/metrics` (9091) | SnapshotsIngestedTotal, DriftEventsTotal |
| lokilinux-frontend | `/health` (3000) | Liveness probe |
| postgres | — | Container health check |
| nats | 8222 | NATS monitoring endpoint |
| redis | — | Container health check |

### 10.7 Environment Variables (57 vars, 15 groups)

Full reference in `.env.example`. Key groups:
- **Platform**: `ENVIRONMENT`, `PLATFORM_HOSTNAME`, `LOKILINUX_VERSION`
- **Database**: `POSTGRES_*`, `PGBOUNCER_*`, `TIMESCALE_*`
- **Cache/Events**: `REDIS_URL`, `NATS_URL`
- **Auth**: `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL`
- **gRPC**: `GRPC_PORT`, `AGENT_CERT_DIR`, `CA_*`, `SERVER_*`
- **Agent**: `AGENT_VERSION`, `AGENT_HEARTBEAT_INTERVAL` (60s), `AGENT_MAX_OFFLINE_DAYS` (30)
- **CVE**: `CVE_FEED_UPDATE_INTERVAL` (86400s), `NVD_API_KEY`
- **Notifications**: `SMTP_*`, `SLACK_*` (disabled by default)

---

## Appendix

### A.1 DB Migration History (25 Alembic Migrations)

| ID | Migration | Tables Added |
|----|-----------|-------------|
| 001 | Initial schema | Core agent, job, CVE, audit tables |
| 002–014 | Iterative additions | Agent FQDN, packages checksum, hardware, ports, categories, projects, ansible entities, health totals |
| 015 | Compliance baseline + inventory | Baseline, BaselineVersion, InventoryBlob/Snapshot/Delta |
| 016 | Compliance policy engine | ComplianceRule, PolicySet, PolicyAssignment, CEL rules |
| 017 | Compliance drift + FIM | DriftEvent, DriftDetail, FileHash, FileChange |
| 018 | Compliance remediation | RemediationPlan, RemediationAction |
| 019 | Compliance reports | ComplianceReport |
| 020–024 | Scope/dedup/alert/policy fixes | Schema refinements, alert dedup, policy engine Phase 1 |

### A.2 Protobuf Message Types (20+)

Key messages in `proto/lokilinux.proto`:
- `AgentHeartbeatRequest` / `AgentHeartbeatResponse` — bidirectional
- `SystemStatus` — hostname, OS, kernel, CPU, memory, disks, network, ports
- `AgentHealth` — status enum (HEALTHY/DEGRADED/UNHEALTHY) + resource usage
- `JobRequest` / `JobResult` — job lifecycle with state enum
- `MetricsData` — metric name + value + tags
- `Package` / `Vulnerability` — package inventory + CVE matches
- `PolicyConfig` — policy rules
- `PluginInstallRequest` / `PluginInstallResult` — plugin lifecycle

### A.3 Compliance Data Model Summary

| Table | Type | Purpose |
|-------|------|---------|
| `baselines` | regular | Baseline definitions with scope |
| `baseline_versions` | regular | Versioned content (DRAFT→PUBLISHED) |
| `baseline_approvals` | regular | Ed25519 signing + approval chain |
| `baseline_effective` | regular | Materialized merged state per agent |
| `inventory_blobs` | regular | Canonical JSON + BLAKE3 per domain |
| `inventory_snapshots` | hypertable | Point-in-time agent state |
| `inventory_deltas` | hypertable | Changed keys between snapshots |
| `rule_evaluations` | hypertable | PASS/FAIL per rule per agent |
| `compliance_scores` | hypertable | Aggregate scores per agent/category |
| `drift_events` | hypertable | Configuration drift occurrences |
| `drift_details` | hypertable | JSON-pointer field diffs |
| `file_hashes` | regular | BLAKE3 file hashes per agent |
| `file_changes` | hypertable | File additions/modifications/deletions |
| `remediation_plans` | regular | Remediation plan workflow |
| `remediation_actions` | regular | Individual remediation steps |
| `compliance_reports` | regular | Generated report metadata |

### A.4 Key Architecture Decisions (Hybrid Compliance)

| Decision | Rationale |
|----------|-----------|
| D1 — Hybrid topology | Go for CPU-bound hot path (ingest, drift, evaluation, scheduling); FastAPI for user-facing CRUD (auth, audit, job engine) |
| D2 — Per-domain delta sync | BLAKE3 hashes every heartbeat, full body only on resync |
| D3 — Compiled-in collectors | 24 domains compiled into agent binary (not plugins) for security + performance |
| D4 — CEL over OVAL | CEL (Common Expression Language) for rule evaluation instead of OVAL XML — simpler, faster, embeddable |
| D5 — Materialized effective baselines | Pre-computed merged baseline per agent for O(1) drift lookup |
| D6 — NATS KV leader election | Single active scheduler replica at any time; prevents duplicate job dispatch |
| D7 — pgx + hand-written SQL | Direct PostgreSQL access from Go compliance service (no ORM) |
| D8 — Ed25519 baseline signing | Cryptographic integrity for baseline content approval |
| D9 — New charting dependency | Frontend needs one chart library for heatmaps, risk matrices, trends |
