# LokiLinux — Platform Architecture & Implementation Specification

**Versiune:** 1.0  
**Status:** Enterprise Architecture Design  
**Data:** 2026

---

## I. EXECUTIVE OVERVIEW

LokiLinux este o platformă de management și remediere a flotei Linux enterprise-grade, construită cu arhitectură moderna, agent lightweight și sistem de plugin modular. Scopul prim: centralizare, monitoring, patch management, remediere vulnerabilități și compliance pe scale 10K-100K+ servere Linux.

---

## II. ARHITECTURA GENERALĂ

```
┌─────────────────────────────────────────────────────────────────┐
│                        LokiLinux Platform                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │   Web UI        │  │   API GW     │  │   Plugin        │   │
│  │   (Nuxt 4)      │  │   (FastAPI)  │  │   Marketplace   │   │
│  └────────┬────────┘  └──────┬───────┘  └────────┬────────┘   │
│           │                  │                     │             │
│  ┌────────┴──────────────────┴─────────────────────┴────────┐  │
│  │         CORE SERVICES LAYER (async FastAPI)              │  │
│  ├────────────────────────────────────────────────────────────┤  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │  │
│  │  │ Agent Mgmt   │  │ Job Engine   │  │ Policy       │   │  │
│  │  │ Service      │  │ Service      │  │ Engine       │   │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │  │
│  │  │ Inventory    │  │ CVE Engine   │  │ Event Bus    │   │  │
│  │  │ Service      │  │ Service      │  │ Service      │   │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │  │
│  │  │ Auth/RBAC    │  │ Audit Logs   │  │ Alert        │   │  │
│  │  │ Service      │  │ Service      │  │ Service      │   │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│           │              │              │              │         │
│  ┌────────┴──────────────┴──────────────┴──────────────┴──────┐  │
│  │         DATA & MESSAGE LAYER                             │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │                                                          │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │  │
│  │  │ PostgreSQL  │  │ NATS Event   │  │ Redis Cache    │ │  │
│  │  │ (inventory, │  │ Bus (async)  │  │ (sessions,     │ │  │
│  │  │ policies,   │  │              │  │  discovery)    │ │  │
│  │  │ jobs, CVE)  │  │              │  │                │ │  │
│  │  └─────────────┘  └──────────────┘  └────────────────┘ │  │
│  │                                                          │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │ TimescaleDB / VictoriaMetrics (time-series)      │  │  │
│  │  │ - Metrics historice din agenți                   │  │  │
│  │  │ - Metrici sistem (CPU, RAM, disk, network)       │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│           │                                  │                  │
│  ┌────────┴──────────────────────────────────┴──────────────┐  │
│  │         EXTERNAL INTEGRATIONS                           │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │  Zabbix │ Prometheus │ Grafana │ LDAP │ Slack │ PagerDuty  │
│  │  (via plugin marketplace architecture)                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
         ▲
         │
         │ gRPC + mTLS
         │ (outbound only)
         │
         │
    ┌────┴────────────────────────────────────────────────────┐
    │         LINUX SERVERS (FLEET)                           │
    ├─────────────────────────────────────────────────────────┤
    │                                                          │
    │  Server 1                 Server 2      ...  Server N   │
    │  ┌──────────────┐         ┌──────────┐     ┌──────────┐ │
    │  │ LokiLinux    │         │ LokiLinux│     │LokiLinux │ │
    │  │ Agent (GO)   │         │ Agent    │     │ Agent    │ │
    │  │              │         │          │     │          │ │
    │  │ ┌──────────┐ │         └──────────┘     └──────────┘ │
    │  │ │ Core     │ │                                        │
    │  │ │ Modules  │ │         Debian/Ubuntu                │
    │  │ ├──────────┤ │         RHEL/Rocky/AlmaLinux         │
    │  │ │ Pkg Mgr  │ │         Oracle Linux                 │
    │  │ │ Inv Coll │ │                                        │
    │  │ │ CVE Rep  │ │                                        │
    │  │ │ Job Exec │ │                                        │
    │  │ │ Metrics  │ │                                        │
    │  │ │ Cache    │ │                                        │
    │  │ └──────────┘ │                                        │
    │  │              │                                        │
    │  │ ┌──────────┐ │                                        │
    │  │ │ Plugins  │ │  (installed from marketplace)         │
    │  │ │ (sandboxed)                                        │
    │  │ └──────────┘ │                                        │
    │  └──────────────┘                                        │
    │       │                                                  │
    │       └──► systemd service                              │
    │            low resource footprint                       │
    │            works offline (local retry/cache)            │
    │            periodic heartbeat                           │
    │                                                          │
    └──────────────────────────────────────────────────────────┘
```

---

## III. COMPONENTE PRINCIPALE

### 3.1 CONTROL PLANE (Server Central)

#### 3.1.1 API Gateway (FastAPI)
- **Port:** 443 (HTTPS), 50051 (gRPC)
- **Responsabilități:**
  - Route HTTP requests la servicii microservices
  - gRPC gateway pentru agent communication
  - Rate limiting, request validation
  - mTLS certificate verification
  - Request/response logging
  - GraphQL endpoint (optional, pentru UI complex)
- **Scalare:** Load balancer (NGINX/Envoy), horizontal scaling pe K8s sau bare-metal

#### 3.1.2 Authentication & Authorization Service
- **Subsistem RBAC:** 
  - Resource-based ACL (servere, grupuri, plugin-uri)
  - Role hierarchy: Admin, Manager, Operator, Viewer
  - LDAP/OAuth2 integration ready
- **Token Management:**
  - JWT short-lived (15 min), refresh tokens (7 days)
  - Agent mTLS certificates (long-lived, 1 year)
  - API keys pentru plugin-uri și integrări externe
- **Audit Trail:**
  - Log fiecare acces la resurse (inventory, jobs, policy changes)
  - Retention: 2 ani

#### 3.1.3 Agent Management Service
- **Discovery & Registration:**
  - Agent enrollment via token (one-time, auto-revoke)
  - Certificate generation & distribution (PKI)
  - Heartbeat synchronization (agent → platform) la 30-60s
  - Health monitoring per agent
- **Agent State Machine:**
  ```
  PENDING → REGISTERED → ACTIVE ──┬──→ INACTIVE
                                   ├──→ UNHEALTHY
                                   └──→ MAINTENANCE
  ```
- **Commands:**
  - Agent upgrade (canary → staged rollout)
  - Policy sync
  - Configuration push
  - Plugin installation/update

#### 3.1.4 Job Engine Service
- **Job Types:**
  - `PACKAGE_UPDATE` — update specific packages
  - `SECURITY_PATCH` — security-only updates
  - `INVENTORY_SCAN` — refresh local inventory
  - `CVE_SCAN` — check vulnerabilities
  - `CUSTOM_COMMAND` — execute whitelisted commands
  - `REMEDIATION` — auto-fix vulnerabilities
- **State Machine:**
  ```
  QUEUED → SCHEDULED → PENDING → RUNNING → COMPLETED
                                        ├→ FAILED
                                        ├→ TIMEOUT
                                        └→ CANCELLED
  ```
- **Distribution:**
  - Single server, server group, tag-based, dynamic filters
  - Batch scheduling (avoid thundering herd)
  - Maintenance window enforcement
  - Rollback capability (package version pinning)
- **Idempotency:**
  - Job ID tracking, deduplication
  - Restart-safe (check already-executed steps)

#### 3.1.5 Policy Engine Service
- **Policy Types:**
  - `UPDATE_POLICY` — when/how to update packages
  - `SECURITY_POLICY` — CVE vulnerability response
  - `COMPLIANCE_POLICY` — regulatory requirements
  - `MAINTENANCE_POLICY` — maintenance windows
  - `PLUGIN_POLICY` — which plugins allowed per server
- **Evaluation:**
  - Rule matching (REGO-like DSL sau CEL)
  - Server matching (tags, hostname patterns, distro, custom attributes)
  - Time-based activation
  - Conflict resolution
- **Application:**
  - Via NATS event: policy change → push to agents
  - Agent caches local copy (resume offline)

#### 3.1.6 Inventory Service
- **Data Collection:**
  - System info: OS, kernel, CPU, RAM, disk, network
  - Installed packages (version, architecture, source)
  - Running services (systemd units)
  - Custom facts (YAML/JSON format per server)
- **Aggregation:**
  - Collect from agents on heartbeat
  - Delta sync (only changes)
  - Deduplication
- **Search/Filter:**
  - By OS, kernel version, package, service
  - Full-text search
  - Tag-based queries

#### 3.1.7 CVE Engine Service
- **Feed Sources:**
  - Ubuntu Security Notices (via API)
  - Debian Security Tracker (via API)
  - RedHat CVE feeds (via Errata API)
  - NVD API (NIST National Vulnerability Database)
  - Optional: Trivy database, OpenSCAP OVAL
- **Local CVE Database:**
  - PostgreSQL table: `cve`, `package_vulnerability`, `cve_package_mapping`
  - Sync daily
  - Retention: 2 years
- **Vulnerability Matching:**
  - Per server: inventory packages vs. CVE database
  - Return: [CVE ID, severity (CVSS), affected packages, fix version]
  - Risk scoring (CVSS + system importance)
- **Remediation Recommendation:**
  - Auto-generate update commands
  - Group CVE-uri by package
  - Suggest batch updates vs. individual

#### 3.1.8 Event Bus Service (NATS)
- **Topics:**
  ```
  agent.{agent_id}.heartbeat
  agent.{agent_id}.job.update
  policy.changed
  cve.database.updated
  plugin.installed
  alert.triggered
  compliance.drift
  ```
- **Subscribers:**
  - Services listen to relevant topics
  - Event-driven architecture (vs. polling)
  - Fan-out pub/sub
  - Message retention (24h)

#### 3.1.9 Plugin Marketplace Service
- **Registry:**
  - Plugin metadata (name, version, description, author, icon)
  - Manifest validation (schema)
  - Permission declaration
  - Dependency graph
  - Versioning & SemVer compliance
- **Installation:**
  - Download plugin binary/archive
  - Signature verification (GPG/cosign)
  - Create isolated service + API routes
  - Install dependencies (Python/Node modules if needed)
  - Enable/disable per server or globally
- **Lifecycle:**
  - Hook: `on_install`, `on_enable`, `on_update`, `on_remove`
  - Plugin-specific config (JSON schema validation)
  - Isolated data storage (per-plugin PostgreSQL schema)

#### 3.1.10 Alerting & Notification Service
- **Alert Types:**
  - `AGENT_OFFLINE` — no heartbeat > 5 min
  - `CVE_CRITICAL` — critical vulnerability detected
  - `POLICY_VIOLATION` — server drift from policy
  - `JOB_FAILED` — job execution error
  - `COMPLIANCE_ISSUE` — missing updates, kernel versions
- **Channels:**
  - Email (SMTP)
  - Slack/Teams (via webhook)
  - PagerDuty integration
  - Custom webhooks
- **Escalation:**
  - Escalate unresolved alerts (1h, 24h)
  - Alert aggregation (deduplicate noisy alerts)
  - Incident correlation

#### 3.1.11 Audit Logging Service
- **Logged Events:**
  - User actions (login, resource access, policy changes)
  - Agent actions (job execution, policy sync)
  - System changes (plugin install, configuration)
  - Compliance actions (remediation)
- **Storage:** PostgreSQL `audit_logs` table
- **Retention:** 2 years
- **Query:** Full-text search, time-range filters

---

### 3.2 LINUX AGENT (Per-Server Component)

#### 3.2.1 Agent Architecture

**Binary:** Static-linked Go executable (~20-30 MB)
- Cross-compiled: linux/amd64, linux/arm64, etc.
- No runtime dependencies (no Python, Node.js, libc)
- Packaged as: .deb, .rpm
- Init system: systemd service + timer units

**Process Model:**
- Single daemon process (manager)
- Forked subprocesses for:
  - Job execution (isolated environment)
  - Plugin execution (sandboxed, separate PID namespace)
  - Metrics collection (non-blocking)

**Resource Footprint:**
- Idle RAM: <50 MB
- Idle CPU: <1%
- Network: 2-5 MB/day (heartbeat + metrics)

#### 3.2.2 Core Agent Modules

**A. System Information Collector**
- Collects on startup, refresh on heartbeat:
  ```
  - uname -a (kernel, hostname, arch)
  - lsb_release (distro, version)
  - /proc/cpuinfo (CPU count, model, flags)
  - /proc/meminfo (RAM, swap)
  - df (disk free/total per mount)
  - systemd-analyze (boot time)
  - lspci, lsusb (hardware)
  - /etc/os-release (standardized OS info)
  ```
- Sends delta only if changed

**B. Package Manager Module**
- Supported:
  - apt/dpkg (Debian/Ubuntu)
  - dnf/yum/rpm (RHEL/CentOS/Rocky/AlmaLinux)
  - zypper (SUSE, optional)
- Operations:
  ```
  - List installed packages: dpkg -l, rpm -qa
  - Check updates: apt list --upgradable, dnf check-update
  - Install: apt install -y, dnf install -y
  - Remove: apt remove -y, dnf remove -y
  - Downgrade/pin: apt-mark hold, dnf versionlock
  - Repository management: add-apt-repository, yum-config-manager
  ```
- Caching:
  - Cache package list locally (TTL 1 hour)
  - Offline mode: serve cached list if disconnected
  - Auto-refresh on policy change

**C. Vulnerability Reporting Module**
- Local CVE matching:
  - Download/cache CVE database (daily sync from platform)
  - Cross-reference installed packages vs. CVE DB
  - Return: list of [package, CVE, severity, fix version]
- Zero-network overhead: all matching done locally
- Report format: JSON, sent to platform on heartbeat

**D. Job Execution Module**
- Job types supported:
  - `PACKAGE_UPDATE` → invoke package manager
  - `SECURITY_PATCH` → filtered package updates (security only)
  - `SERVICE_RESTART` → systemctl restart <service>
  - `CUSTOM_COMMAND` → execute from whitelist
  - `FACT_COLLECTION` → run custom fact script
- Execution sandbox:
  - Forked subprocess (separate PID, cgroup, namespace)
  - ulimit resource constraints
  - seccomp filter (if enabled)
  - stdout/stderr captured, sent to platform
- Safety:
  - Whitelist enforcement (hardcoded commands + policies)
  - Timeout enforcement (max 1 hour per job)
  - Rollback capability: revert package downgrades
  - No interactive shell access

**E. Metrics Collection Module**
- Periodic collection (every 5 min):
  ```
  - CPU: /proc/stat → usage %, context switches
  - Memory: /proc/meminfo → used, free, available
  - Disk: /proc/diskstats → read/write ops, bytes
  - Network: /proc/net/dev → packet loss, errors
  - systemd-analyze (boot perf)
  - apt/dnf cache stats
  ```
- Batching: send aggregated metrics every 5 min
- Compression: gzip before transport

**F. Local Cache & Offline Mode**
- SQLite local database:
  ```
  - Last inventory snapshot
  - Last job results (100 entries)
  - Local CVE database (for matching)
  - Policy cache
  - Metrics history (48h)
  - Command whitelist (updated on policy sync)
  ```
- Behavior when disconnected:
  - Queue jobs locally (max 1000)
  - Serve inventory from cache
  - Perform local CVE matching
  - Retry failed jobs on reconnect
  - Max offline duration: 30 days (then manual intervention)

**G. Plugin Loader Module**
- Plugin discovery:
  - /opt/lokilinux/plugins/{plugin_name}/manifest.yaml
  - /opt/lokilinux/plugins/{plugin_name}/bin/{plugin_binary}
- Sandboxing:
  ```
  - Separate namespace (Linux namespaces)
  - cgroup resource limits
  - seccomp sandbox
  - IPC via local gRPC (Unix socket)
  ```
- Lifecycle:
  - Load on agent startup
  - Unload on SIGTERM
  - Auto-restart on crash (max 3 retries)
- Communication:
  - Plugin → Agent gRPC (bidirectional)
  - Agent → Plugin data exchange (protobuf)
  - Plugin → External API (if plugin declares need)

#### 3.2.3 Agent Communication Protocol

**Transport:** gRPC + protobuf (binary)
- Multiplexing: single mTLS connection for all communication
- Compression: automatic gzip for large payloads
- Keepalive: gRPC keepalive pings (30s interval)

**Connection Model:**
```
Agent → (outbound HTTPS/gRPC) → API Gateway
↓
mTLS verification (agent cert + CA)
↓
Request → ServiceName.MethodName
↓
Response → StreamingResponse (for long-running jobs)
```

**Heartbeat Protocol:**
```protobuf
message AgentHeartbeat {
  string agent_id = 1;
  int64 timestamp = 2;
  SystemInfo system = 3;
  repeated Package packages = 4;
  repeated string running_services = 5;
  map<string, string> custom_facts = 6;
  repeated CVEMatch vulnerabilities = 7;
  AgentHealth health = 8;
  repeated MetricPoint recent_metrics = 9;
}

response: HeartbeatAck {
  repeated Job pending_jobs = 1;
  Policy policy = 2;
  map<string, PluginAction> plugin_actions = 3;
  int64 next_heartbeat_interval = 4;
}
```

**Job Execution Stream:**
```protobuf
message JobRequest {
  string job_id = 1;
  string job_type = 2;
  map<string, string> parameters = 3;
  int32 timeout_seconds = 4;
}

stream JobStatus {
  string job_id = 1;
  JobState state = 2;  // RUNNING, COMPLETED, FAILED
  string output = 3;   // stdout/stderr
  int32 exit_code = 4;
  int64 timestamp = 5;
}
```

#### 3.2.4 Agent Configuration

**File:** `/etc/lokilinux/agent.yaml`
```yaml
platform:
  url: "https://platform.example.com:443"
  grpc_endpoint: "grpc.example.com:50051"
  
identity:
  agent_id: "agent-uuid"  # set on enrollment
  cert_path: "/etc/lokilinux/certs/agent.crt"
  key_path: "/etc/lokilinux/certs/agent.key"
  ca_path: "/etc/lokilinux/certs/ca.crt"
  
heartbeat:
  interval_sec: 60
  timeout_sec: 30
  retry_backoff_max: 600  # 10 min
  
cache:
  enabled: true
  path: "/var/lib/lokilinux"
  sqlite_db: "/var/lib/lokilinux/agent.db"
  retention_days: 30
  
job_execution:
  max_parallel_jobs: 2
  timeout_seconds: 3600
  sandbox_enabled: true
  
plugins:
  enabled: true
  path: "/opt/lokilinux/plugins"
  isolation: "namespace"  # or "none" if disabled
  
logging:
  level: "info"
  output: "syslog"  # or "file:/var/log/lokilinux/agent.log"
```

---

### 3.3 FRONTEND (Nuxt 4 + Vue 3)

#### 3.3.1 Application Structure

```
app/
├── layouts/
│   ├── default.vue          # Main dashboard layout
│   ├── auth.vue             # Login/enrollment layout
│   └── admin.vue            # Admin settings layout
├── pages/
│   ├── index.vue            # Dashboard home
│   ├── servers/
│   │   ├── index.vue        # Server list/inventory
│   │   └── [id]/
│   │       ├── index.vue    # Server detail
│   │       ├── packages.vue # Packages tab
│   │       ├── vulnerabilities.vue
│   │       ├── jobs.vue
│   │       └── metrics.vue
│   ├── jobs/
│   │   ├── index.vue        # Job queue + history
│   │   ├── create.vue       # Create job wizard
│   │   └── [id]/status.vue  # Job detail + logs
│   ├── policies/
│   │   ├── index.vue        # Policy list
│   │   ├── create.vue       # Policy editor
│   │   └── [id]/index.vue   # Edit policy
│   ├── plugins/
│   │   ├── index.vue        # Installed plugins
│   │   ├── marketplace.vue  # Plugin marketplace
│   │   └── [id]/config.vue  # Plugin settings
│   ├── vulnerabilities/
│   │   ├── index.vue        # CVE dashboard (global)
│   │   ├── [cve_id]/index.vue
│   │   └── remediation.vue  # Remediation plan generator
│   ├── alerts/
│   │   ├── index.vue        # Active alerts
│   │   └── [id]/index.vue
│   ├── audit/
│   │   └── index.vue        # Audit log viewer
│   ├── admin/
│   │   ├── index.vue        # Admin panel
│   │   ├── users.vue        # User management
│   │   ├── rbac.vue         # Role/permission management
│   │   ├── integrations.vue # Zabbix/external integrations
│   │   └── settings.vue     # Platform settings
│   └── auth/
│       ├── login.vue
│       ├── enroll.vue       # Agent enrollment UI
│       └── mfa.vue
├── components/
│   ├── ServerStatusCard.vue
│   ├── CVEScorecard.vue
│   ├── JobProgressBar.vue
│   ├── PolicyEditor.vue
│   ├── PackageComparisonTable.vue
│   └── ... (50+ components)
├── composables/
│   ├── useAuth.ts
│   ├── useServers.ts
│   ├── useJobs.ts
│   ├── useCVE.ts
│   ├── useMetrics.ts
│   └── ... (15+ composables)
├── stores/
│   ├── auth.ts              # Pinia store
│   ├── servers.ts
│   ├── jobs.ts
│   ├── cve.ts
│   ├── ui.ts
│   └── notifications.ts
├── types/
│   ├── agent.ts
│   ├── job.ts
│   ├── policy.ts
│   ├── cve.ts
│   ├── server.ts
│   └── api.ts
├── utils/
│   ├── formatting.ts        # CVSS score display, time formatting
│   ├── api.ts               # API client wrapper
│   ├── websocket.ts         # Real-time updates
│   └── validators.ts
└── app.vue
```

#### 3.3.2 Key Dashboards

**A. Fleet Dashboard (Home)**
- Server overview: total, healthy, unhealthy, offline
- CVE summary: critical, high, medium by severity
- Active jobs: in-progress, scheduled
- Alert feed: recent alerts, status
- Compliance: policy violations, drift
- Network graph: agent distribution map

**B. Server Inventory**
- List: sortable table (name, OS, kernel, uptime, CVE count, last heartbeat)
- Filters: by OS, distro version, CVE severity, tag, agent status
- Bulk actions: update, install plugin, change policy
- Quick actions: force heartbeat, view details, SSH-like (no terminal, just info)

**C. Server Detail Page**
- Tabs:
  1. **Overview:** status, specs, last heartbeat, agent version
  2. **Packages:** list installed packages, check updates, trigger update job
  3. **Vulnerabilities:** CVE-uri per package, CVSS scores, remediation steps
  4. **Jobs:** job history, running jobs, job details + logs
  5. **Metrics:** time-series graphs (CPU, RAM, disk, network last 7 days)
  6. **Policies:** applied policies, compliance status
  7. **Events:** changelog, last actions, audit

**D. Job Management**
- Create job wizard:
  1. Select job type (update, security patch, custom command, etc.)
  2. Select targets (single server, group, dynamic filter)
  3. Configure parameters (package list, maintenance window, etc.)
  4. Schedule (immediate, maintenance window, recurring)
  5. Approval (if required by policy)
- Job queue: pending jobs sorted by scheduled time
- Job history: completed/failed jobs, logs, rollback option
- Real-time streaming: job progress, stdout/stderr

**E. CVE Management**
- Global CVE dashboard:
  - Vulnerability trend (last 30 days: new CVE-uri)
  - Severity distribution (pie chart)
  - Most affected packages (top 10)
  - Servers by risk score
- CVE detail page:
  - Description, CVSS, affected packages
  - Servers affected
  - Recommended remediation
  - One-click remediation (bulk update)
- Remediation planner:
  - Auto-generate update plan (group CVE-uri, minimize restarts)
  - Simulate impact (affected services)
  - Schedule with maintenance windows

**F. Policy Editor**
- Visual policy builder:
  - Rule conditions (distro, kernel version, server tags, custom facts)
  - Rule actions (auto-update, security-only, notification, escalation)
  - Time-based activation (maintenance windows)
- Policy validation:
  - Preview matching servers
  - Conflict detection
  - Dry-run (simulation)
- Policy versioning + rollback

**G. Plugin Marketplace**
- Browse plugins: name, icon, rating, downloads
- Install flow:
  1. Select plugin
  2. Review permissions
  3. Review config schema
  4. Apply to server(s)
  5. Monitor plugin health
- Installed plugins:
  - Enable/disable per server or globally
  - Configure (form-based or JSON editor)
  - View logs
  - Manage dependencies
  - Update/uninstall

**H. Alerting**
- Alert console:
  - Current alerts (sortable, filterable by severity, type)
  - Acknowledge/resolve actions
  - Alert history
- Alert rules UI:
  - Define custom alert conditions
  - Notification channels + routing
  - Escalation policies

**I. Admin Panel**
- User management: create, edit, delete, assign roles
- RBAC management: define custom roles, permissions matrix
- External integrations: Zabbix API config, LDAP sync
- Platform settings: CVE feed frequency, agent timeout, storage retention
- License management (if applicable)
- Backup/restore: database snapshots, disaster recovery

#### 3.3.3 Real-Time Features
- WebSocket connection:
  - Job progress streaming
  - Agent health status (connected/disconnected)
  - Alert notifications (push)
  - Metrics real-time (time-series live update)
- Update strategy:
  - Pinia stores + composables for state management
  - Optimistic updates for responsive UI
  - Conflict resolution (server-side wins)

---

## IV. PLUGIN SYSTEM ARCHITECTURE

### 4.1 Plugin Types

#### Type 1: External Integrations
- **Purpose:** Sync data from external systems (Zabbix, Prometheus, LDAP)
- **Where:** Control plane (FastAPI service)
- **Example:** Zabbix Connector
  - Polls Zabbix API for hosts/groups/alerts
  - Correlates with LokiLinux inventory
  - Maps Zabbix maintenance → LokiLinux maintenance
  - Enriches alerts with Zabbix metadata

#### Type 2: Custom Dashboards & Reports
- **Purpose:** Extend UI with domain-specific views
- **Where:** Frontend (Nuxt/Vue)
- **Example:** Docker Integration Dashboard
  - Show container status per server
  - Container image vulnerability scanning
  - Container registry integration

#### Type 3: Agent-Side Extensions
- **Purpose:** Extend agent capabilities on servers
- **Where:** Agent (installed in /opt/lokilinux/plugins/{name}/)
- **Example:** CrowdSec Integration
  - Local crowdsec daemon on each server
  - Threat detection, IP blocking
  - Report to platform

#### Type 4: Notification & Alerting
- **Purpose:** Custom notification channels
- **Where:** Control plane (FastAPI)
- **Example:** OpsGenie, ServiceNow integration
  - Receive alerts from platform
  - Create incidents, update tickets
  - Bidirectional sync

### 4.2 Plugin Manifest Specification

**File:** `manifest.yaml`
```yaml
name: "zabbix-connector"
display_name: "Zabbix Integration"
version: "1.0.0"
author: "LokiLinux Team"
description: "Synchronize servers and alerts from Zabbix"
icon_url: "https://cdn.example.com/zabbix.png"
type: "control-plane"  # control-plane, agent, ui, notification

# Semantic versioning
min_platform_version: "1.0.0"
max_platform_version: "2.0.0"

# Plugin entrypoint
entrypoint:
  type: "grpc"  # or "rest", "python", "nodejs"
  service_name: "ZabbixConnectorService"
  address: "unix:///run/lokilinux-plugins/zabbix.sock"

# API routes exposed
routes:
  - method: "GET"
    path: "/api/zabbix/hosts"
    handler: "get_hosts"
  - method: "POST"
    path: "/api/zabbix/sync"
    handler: "sync_from_zabbix"

# Permissions required
permissions:
  - "inventory:read"
  - "alert:write"
  - "external:http"  # make HTTP requests to Zabbix API

# Configuration schema (JSON Schema)
config_schema:
  type: "object"
  properties:
    zabbix_url:
      type: "string"
      description: "Zabbix server URL"
      example: "https://zabbix.example.com"
    zabbix_api_token:
      type: "string"
      description: "Zabbix API token (stored encrypted)"
      format: "password"
    sync_interval_minutes:
      type: "integer"
      minimum: 5
      default: 30
    enabled:
      type: "boolean"
      default: true
  required: ["zabbix_url", "zabbix_api_token"]

# Hooks
hooks:
  on_install: "run_schema_migrations"
  on_update: "handle_version_upgrade"
  on_enable: "start_sync_loop"
  on_disable: "stop_sync_loop"
  on_remove: "cleanup_resources"

# Dependencies
dependencies:
  - name: "postgres"
    version: ">=12"
  - name: "nats"
    version: ">=2.0"

# Resource limits
resources:
  max_memory_mb: 256
  max_cpu_cores: 1
  max_network_bandwidth_mbps: 10

# Health check
health_check:
  type: "http"
  url: "http://localhost:8080/health"
  interval_seconds: 30
  timeout_seconds: 5

# Versioning & update strategy
update_strategy: "rolling"  # or "blue-green", "canary"
```

### 4.3 Plugin Development Kit (SDK)

**Python SDK Example:**
```python
# pip install lokilinux-sdk

from lokilinux_sdk import LokiPlugin, PluginConfig, Event, http_endpoint

class ZabbixConnectorPlugin(LokiPlugin):
    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.zabbix_url = config.get("zabbix_url")
        self.api_token = config.get("zabbix_api_token")
    
    async def on_install(self):
        """Called during plugin installation"""
        await self.db.create_tables("""
            CREATE TABLE zabbix_sync_state (
                id SERIAL PRIMARY KEY,
                last_sync TIMESTAMP,
                synced_host_count INTEGER
            )
        """)
    
    async def on_enable(self):
        """Called when plugin is enabled"""
        self.logger.info("Zabbix connector enabled")
        # Start background sync
        asyncio.create_task(self.sync_loop())
    
    @http_endpoint(method="POST", path="/sync")
    async def sync_from_zabbix(self, request):
        """Expose HTTP endpoint"""
        hosts = await self.fetch_zabbix_hosts()
        for host in hosts:
            await self.platform_api.inventory.add_server(
                name=host["name"],
                ip=host["ip"],
                source="zabbix",
                metadata={"zabbix_hostid": host["hostid"]}
            )
        return {"synced": len(hosts)}
    
    async def sync_loop(self):
        """Background task: periodically sync Zabbix"""
        while True:
            try:
                await self.sync_from_zabbix()
                interval = self.config.get("sync_interval_minutes", 30)
                await asyncio.sleep(interval * 60)
            except Exception as e:
                self.logger.error(f"Sync error: {e}")
                await asyncio.sleep(300)  # retry in 5 min
    
    @self.subscribe("cve.critical_detected")
    async def on_critical_cve(self, event: Event):
        """Subscribe to platform events"""
        cve_id = event.data["cve_id"]
        affected_servers = event.data["servers"]
        # Create Zabbix problem ticket
        await self.create_zabbix_problem(cve_id, affected_servers)
```

**Go SDK Example (for agent plugins):**
```go
// go get github.com/lokilinux/agent-sdk

package main

import (
	"github.com/lokilinux/agent-sdk/plugin"
)

type DockerManagerPlugin struct {
	client *plugin.AgentClient
}

func (p *DockerManagerPlugin) GetContainerStatus() ([]Container, error) {
	output, err := p.client.ExecuteCommand("docker ps --format json")
	if err != nil {
		return nil, err
	}
	// Parse output...
	return containers, nil
}

func (p *DockerManagerPlugin) ScanContainerVulnerabilities() ([]Vulnerability, error) {
	// Integration with Trivy
	containers, _ := p.GetContainerStatus()
	// Scan each container image...
	return vulns, nil
}

func main() {
	plugin.Register(&DockerManagerPlugin{})
	plugin.Start()
}
```

### 4.4 Plugin Lifecycle & Management

**State Machine:**
```
PENDING_INSTALL
    ↓
INSTALLING (download, verify signature, extract)
    ↓
INSTALLED (but disabled)
    ├────→ ENABLING ──→ ENABLED ──→ DISABLING → DISABLED
    │                                   ↓
    │                           UNINSTALLING → REMOVED
    │                                   ↑
    └──────────────────────────────────┘
```

**Installation Flow:**
1. Admin selects plugin from marketplace
2. Platform downloads plugin archive from registry
3. Verify signature: `cosign verify <archive>`
4. Extract: `/opt/lokilinux/plugins/{plugin_name}/`
5. Run `on_install` hook
6. Database migrations (if needed)
7. Store plugin config in PostgreSQL
8. Mark as INSTALLED

**Enable Flow:**
1. Run `on_enable` hook
2. Start plugin process (systemd or direct)
3. Register API routes
4. Subscribe to relevant events
5. Health check passes → ENABLED

**Update Flow:**
1. Detect new version available
2. Download + verify signature
3. Run blue-green deployment (new version in parallel)
4. Health check on new version
5. If healthy: switch traffic
6. If unhealthy: rollback, keep old version
7. Run `on_update` hook
8. Cleanup old version

### 4.5 Plugin Marketplace

**Registry Structure:**
```
registry.lokilinux.com
├── /api/v1/plugins/
│   ├── list          (GET)
│   ├── search        (POST)
│   ├── {name}        (GET)
│   ├── {name}/{version}/
│   │   ├── manifest.yaml
│   │   ├── plugin-binary.tar.gz
│   │   ├── plugin-binary.tar.gz.sig
│   │   └── CHANGELOG.md
│   └── uploads/      (for private registries)
└── /web/marketplace/ (web UI)
```

**Plugin Discovery in UI:**
- List all available plugins
- Filters: type, category, rating, downloads
- Search by name/description
- Reviews & comments
- Installation statistics
- Security scan results (for binaries)

---

## V. DATABASE DESIGN (PostgreSQL)

### 5.1 Core Tables

```sql
-- ============================================================================
-- AGENTS & INVENTORY
-- ============================================================================

CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(255) UNIQUE NOT NULL,
    
    -- Registration & Status
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',  -- PENDING, REGISTERED, ACTIVE, INACTIVE, UNHEALTHY, MAINTENANCE
    registered_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_heartbeat TIMESTAMP,
    last_heartbeat_ip INET,
    
    -- Identity & Security
    cert_fingerprint VARCHAR(64) UNIQUE,
    cert_valid_from TIMESTAMP,
    cert_valid_until TIMESTAMP,
    
    -- Version
    agent_version VARCHAR(50),
    platform_version VARCHAR(50),
    
    -- Server Metadata
    hostname VARCHAR(255),
    os_family VARCHAR(50),     -- linux
    os_distro VARCHAR(100),    -- debian, ubuntu, rhel, rocky, almalinux
    os_version VARCHAR(50),    -- 20.04, 8.5, etc.
    kernel_version VARCHAR(100),
    arch VARCHAR(50),          -- x86_64, arm64
    
    -- Policy & Configuration
    current_policy_id UUID REFERENCES policies(id),
    plugin_policy_id UUID REFERENCES policies(id),
    
    -- Tagging & Organization
    tags JSONB DEFAULT '{}',
    custom_facts JSONB DEFAULT '{}',
    
    -- Created/Modified
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_status (status),
    INDEX idx_hostname (hostname),
    INDEX idx_os_distro (os_distro),
    INDEX idx_tags (tags),
    INDEX idx_last_heartbeat (last_heartbeat)
);

CREATE TABLE agent_health (
    id SERIAL PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- Health Metrics
    cpu_usage FLOAT,           -- 0-100
    memory_usage FLOAT,        -- 0-100
    disk_usage FLOAT,          -- 0-100
    network_latency_ms FLOAT,
    
    -- Status Flags
    is_disk_full BOOLEAN DEFAULT FALSE,
    is_memory_critical BOOLEAN DEFAULT FALSE,
    connection_failures INTEGER DEFAULT 0,
    
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_agent_id (agent_id),
    INDEX idx_recorded_at (recorded_at)
);

CREATE TABLE packages (
    id SERIAL PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- Package Info
    name VARCHAR(255) NOT NULL,
    version VARCHAR(100) NOT NULL,
    architecture VARCHAR(50),
    
    -- Package Source
    repository VARCHAR(255),
    source_type VARCHAR(50),  -- manual, distro, ppa, etc.
    
    -- Status
    is_security_update_available BOOLEAN DEFAULT FALSE,
    is_update_available BOOLEAN DEFAULT FALSE,
    latest_version VARCHAR(100),
    
    installed_at TIMESTAMP,
    last_update_check TIMESTAMP DEFAULT NOW(),
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    UNIQUE(agent_id, name, version),
    INDEX idx_agent_id (agent_id),
    INDEX idx_update_available (is_update_available),
    INDEX idx_security_update (is_security_update_available)
);

-- ============================================================================
-- VULNERABILITIES & CVE
-- ============================================================================

CREATE TABLE cves (
    id SERIAL PRIMARY KEY,
    cve_id VARCHAR(50) UNIQUE NOT NULL,  -- CVE-YYYY-XXXXX
    
    -- CVE Details
    title TEXT,
    description TEXT,
    cvss_v3_score FLOAT,
    cvss_v3_severity VARCHAR(20),        -- CRITICAL, HIGH, MEDIUM, LOW
    published_date DATE,
    updated_date DATE,
    
    -- References
    nvd_url VARCHAR(255),
    debian_url VARCHAR(255),
    ubuntu_url VARCHAR(255),
    redhat_url VARCHAR(255),
    
    -- CWE Classification
    cwe_ids JSONB DEFAULT '[]',  -- array of CWE IDs
    
    -- Affected Products (generic)
    affected_packages JSONB DEFAULT '{}',  -- {package_name: [versions]}
    
    is_zero_day BOOLEAN DEFAULT FALSE,
    is_actively_exploited BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_cve_id (cve_id),
    INDEX idx_cvss_score (cvss_v3_score),
    INDEX idx_cvss_severity (cvss_v3_severity),
    INDEX idx_published_date (published_date),
    INDEX idx_actively_exploited (is_actively_exploited)
);

CREATE TABLE package_vulnerabilities (
    id SERIAL PRIMARY KEY,
    
    -- Link to CVE
    cve_id VARCHAR(50) NOT NULL REFERENCES cves(cve_id) ON DELETE CASCADE,
    
    -- Link to Package
    package_name VARCHAR(255) NOT NULL,
    distro VARCHAR(100) NOT NULL,        -- debian, ubuntu, rhel, rocky
    
    -- Affected Versions
    affected_versions JSONB NOT NULL,    -- {ranges: [">= 1.0, < 2.0"], fixed_version: "2.0"}
    fixed_version VARCHAR(100),
    
    -- Fix Status
    is_fixed_available BOOLEAN,
    fix_available_date DATE,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    UNIQUE(cve_id, package_name, distro),
    INDEX idx_cve_id (cve_id),
    INDEX idx_package (package_name),
    INDEX idx_distro (distro)
);

CREATE TABLE agent_vulnerabilities (
    id SERIAL PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    cve_id VARCHAR(50) NOT NULL REFERENCES cves(cve_id) ON DELETE CASCADE,
    
    -- Affected Package on Agent
    package_name VARCHAR(255) NOT NULL,
    package_version VARCHAR(100) NOT NULL,
    
    -- Risk Assessment
    cvss_score FLOAT,
    severity VARCHAR(20),
    risk_score FLOAT,                    -- weighted score (CVSS + exploitability + patch availability)
    
    -- Remediation
    fix_available BOOLEAN,
    recommended_action VARCHAR(50),      -- patch, upgrade, monitor, retire
    
    -- Status
    is_remediated BOOLEAN DEFAULT FALSE,
    remediation_date TIMESTAMP,
    remediation_job_id UUID REFERENCES jobs(id),
    
    discovered_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_check TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_agent_id (agent_id),
    INDEX idx_cve_id (cve_id),
    INDEX idx_risk_score (risk_score),
    INDEX idx_severity (severity),
    INDEX idx_is_remediated (is_remediated)
);

-- ============================================================================
-- JOBS & EXECUTION
-- ============================================================================

CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Job Metadata
    name VARCHAR(255) NOT NULL,
    job_type VARCHAR(50) NOT NULL,      -- PACKAGE_UPDATE, SECURITY_PATCH, CVE_SCAN, CUSTOM_COMMAND, REMEDIATION
    description TEXT,
    
    -- Scope
    target_servers JSONB NOT NULL,      -- {agent_ids: [...], filters: {...}}
    total_servers INTEGER,
    
    -- Scheduling
    status VARCHAR(50) NOT NULL DEFAULT 'QUEUED',  -- QUEUED, SCHEDULED, PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, TIMEOUT
    scheduled_time TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Parameters
    parameters JSONB,                    -- job-type specific: {packages: [...], update_only: true}
    
    -- Policy
    policy_id UUID REFERENCES policies(id),
    requires_approval BOOLEAN DEFAULT FALSE,
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMP,
    
    -- Metadata
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_status (status),
    INDEX idx_job_type (job_type),
    INDEX idx_scheduled_time (scheduled_time),
    INDEX idx_created_by (created_by),
    INDEX idx_created_at (created_at)
);

CREATE TABLE job_results (
    id SERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- Execution Status
    status VARCHAR(50) NOT NULL,        -- PENDING, RUNNING, COMPLETED, FAILED, TIMEOUT, SKIPPED
    exit_code INTEGER,
    error_message TEXT,
    
    -- Output
    stdout TEXT,
    stderr TEXT,
    
    -- Metrics
    duration_seconds INTEGER,
    resources_used JSONB,               -- {cpu_percent: 50, memory_mb: 128}
    
    -- Timestamps
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_job_id (job_id),
    INDEX idx_agent_id (agent_id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
);

-- ============================================================================
-- POLICIES
-- ============================================================================

CREATE TABLE policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Metadata
    name VARCHAR(255) NOT NULL,
    description TEXT,
    policy_type VARCHAR(50),            -- UPDATE, SECURITY, COMPLIANCE, MAINTENANCE, PLUGIN
    
    -- Content
    rules JSONB NOT NULL,               -- DSL: conditions, actions, priorities
    
    -- Scope
    target_servers JSONB,               -- {filters: {os: "ubuntu", kernel: "> 5.0"}}
    
    -- Status
    is_enabled BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 100,       -- lower = higher priority
    
    -- Versioning
    version INTEGER DEFAULT 1,
    parent_policy_id UUID REFERENCES policies(id),
    
    -- Timestamps
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_policy_type (policy_type),
    INDEX idx_is_enabled (is_enabled),
    INDEX idx_priority (priority)
);

CREATE TABLE policy_audit (
    id SERIAL PRIMARY KEY,
    policy_id UUID NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    
    -- Change Tracking
    changed_by UUID NOT NULL REFERENCES users(id),
    change_type VARCHAR(50),            -- CREATE, UPDATE, DELETE, ENABLE, DISABLE
    
    old_value JSONB,
    new_value JSONB,
    
    changed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_policy_id (policy_id),
    INDEX idx_changed_at (changed_at)
);

-- ============================================================================
-- PLUGINS
-- ============================================================================

CREATE TABLE plugins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Metadata
    name VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    version VARCHAR(50) NOT NULL,
    
    -- Details
    description TEXT,
    author VARCHAR(255),
    icon_url VARCHAR(512),
    documentation_url VARCHAR(512),
    
    -- Type & Compatibility
    plugin_type VARCHAR(50) NOT NULL,   -- control-plane, agent, ui, notification
    min_platform_version VARCHAR(50),
    max_platform_version VARCHAR(50),
    
    -- Source & Integrity
    source_url VARCHAR(512),
    manifest JSONB NOT NULL,            -- Full manifest.yaml
    
    -- Status
    is_enabled BOOLEAN DEFAULT FALSE,
    is_installed BOOLEAN DEFAULT FALSE,
    installation_status VARCHAR(50),    -- PENDING_INSTALL, INSTALLING, INSTALLED, INSTALLING_FAILED
    
    -- Configuration
    configuration JSONB,                -- User-provided config
    config_schema JSONB,                -- JSON Schema for validation
    
    -- Permissions
    required_permissions JSONB,         -- array of permissions needed
    
    -- Versioning
    is_latest BOOLEAN DEFAULT FALSE,
    security_verified BOOLEAN DEFAULT FALSE,
    
    -- Marketplace
    download_count INTEGER DEFAULT 0,
    rating FLOAT DEFAULT 0,
    
    -- Timestamps
    installed_at TIMESTAMP,
    last_enabled_at TIMESTAMP,
    last_disabled_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_name (name),
    INDEX idx_plugin_type (plugin_type),
    INDEX idx_is_installed (is_installed),
    INDEX idx_is_enabled (is_enabled)
);

CREATE TABLE plugin_installations (
    id SERIAL PRIMARY KEY,
    plugin_id UUID NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,  -- NULL if global
    
    -- Status
    status VARCHAR(50),                 -- PENDING, INSTALLED, ENABLED, DISABLED, ERROR
    error_message TEXT,
    
    -- Configuration
    local_config JSONB,                 -- Per-server/installation config
    
    -- Versioning
    installed_version VARCHAR(50),
    
    -- Timestamps
    installed_at TIMESTAMP,
    enabled_at TIMESTAMP,
    disabled_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_plugin_id (plugin_id),
    INDEX idx_agent_id (agent_id),
    INDEX idx_status (status)
);

-- ============================================================================
-- ALERTS & NOTIFICATIONS
-- ============================================================================

CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Alert Metadata
    title VARCHAR(255) NOT NULL,
    severity VARCHAR(50),               -- CRITICAL, HIGH, MEDIUM, LOW, INFO
    alert_type VARCHAR(100),            -- AGENT_OFFLINE, CVE_CRITICAL, POLICY_VIOLATION, JOB_FAILED
    
    -- Content
    description TEXT,
    context_data JSONB,                 -- related agent, cve, job, etc.
    
    -- Related Resources
    agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    cve_id VARCHAR(50) REFERENCES cves(cve_id) ON DELETE SET NULL,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    policy_id UUID REFERENCES policies(id) ON DELETE SET NULL,
    
    -- Status & Resolution
    status VARCHAR(50) DEFAULT 'ACTIVE',  -- ACTIVE, ACKNOWLEDGED, RESOLVED, EXPIRED
    acknowledged_by UUID REFERENCES users(id),
    acknowledged_at TIMESTAMP,
    resolved_by UUID REFERENCES users(id),
    resolved_at TIMESTAMP,
    
    -- Notifications
    notification_channels JSONB,        -- {email: [...], slack: [...], pagerduty: [...]}
    notified_at TIMESTAMP,
    
    -- Escalation
    escalation_level INTEGER DEFAULT 0,
    escalated_at TIMESTAMP,
    
    -- Timestamps
    triggered_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_severity (severity),
    INDEX idx_alert_type (alert_type),
    INDEX idx_status (status),
    INDEX idx_agent_id (agent_id),
    INDEX idx_cve_id (cve_id),
    INDEX idx_triggered_at (triggered_at)
);

CREATE TABLE alert_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Rule Metadata
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Conditions (CEL/REGO-like DSL)
    conditions JSONB NOT NULL,          -- conditions to trigger alert
    
    -- Actions
    alert_severity VARCHAR(50),
    notification_channels JSONB,        -- {email: [...], slack: [...]}
    escalation_policy UUID REFERENCES alert_rules(id),
    escalation_delay_minutes INTEGER,
    
    -- Status
    is_enabled BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_is_enabled (is_enabled),
    INDEX idx_created_by (created_by)
);

-- ============================================================================
-- USERS & RBAC
-- ============================================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Identity
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    
    -- Authentication
    password_hash VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret VARCHAR(255),
    
    -- Role Assignment
    role_id UUID REFERENCES roles(id),
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_login TIMESTAMP,
    
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_is_active (is_active)
);

CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Role Metadata
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    
    -- Permissions
    permissions JSONB,                  -- array of permission strings
    
    -- Status
    is_builtin BOOLEAN DEFAULT FALSE,
    is_custom BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_name (name)
);

CREATE TABLE role_assignments (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    
    -- Scope (optional)
    scope_type VARCHAR(50),             -- global, server_group, server
    scope_id VARCHAR(255),
    
    assigned_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    UNIQUE(user_id, role_id, scope_type, scope_id),
    INDEX idx_user_id (user_id),
    INDEX idx_role_id (role_id)
);

-- ============================================================================
-- AUDIT LOGS
-- ============================================================================

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    
    -- Actor
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_type VARCHAR(50),             -- user, system, plugin
    actor_name VARCHAR(255),
    
    -- Action
    action VARCHAR(100),                -- create, read, update, delete, execute, remediate
    resource_type VARCHAR(100),         -- agent, job, policy, plugin, cve, vulnerability
    resource_id VARCHAR(255),
    
    -- Details
    changes JSONB,                      -- what changed
    status VARCHAR(50),                 -- success, failure
    error_message TEXT,
    
    -- Context
    source_ip INET,
    user_agent TEXT,
    
    -- Timestamps
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_user_id (user_id),
    INDEX idx_resource_type (resource_type),
    INDEX idx_action (action),
    INDEX idx_timestamp (timestamp)
);

-- ============================================================================
-- METRICS (Time-Series, TimescaleDB extension)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE agent_metrics (
    time TIMESTAMPTZ NOT NULL,
    agent_id UUID NOT NULL,
    
    -- CPU Metrics
    cpu_user FLOAT,
    cpu_system FLOAT,
    cpu_idle FLOAT,
    cpu_count INTEGER,
    
    -- Memory Metrics
    memory_total BIGINT,
    memory_used BIGINT,
    memory_available BIGINT,
    
    -- Disk Metrics
    disk_total BIGINT,
    disk_used BIGINT,
    disk_io_read_bytes BIGINT,
    disk_io_write_bytes BIGINT,
    
    -- Network Metrics
    network_bytes_in BIGINT,
    network_bytes_out BIGINT,
    network_packets_in BIGINT,
    network_packets_out BIGINT,
    
    -- Process Metrics
    process_count INTEGER,
    thread_count INTEGER,
    
    -- Custom Tags
    tags JSONB DEFAULT '{}',
    
    PRIMARY KEY (time, agent_id)
);

SELECT create_hypertable('agent_metrics', 'time', if_not_exists => TRUE);
CREATE INDEX idx_agent_metrics_agent_id_time ON agent_metrics (agent_id, time DESC);

-- ============================================================================
-- SETTINGS & CONFIGURATION
-- ============================================================================

CREATE TABLE settings (
    id SERIAL PRIMARY KEY,
    
    -- Setting Key
    key VARCHAR(255) UNIQUE NOT NULL,
    
    -- Value & Type
    value TEXT,
    value_type VARCHAR(50),             -- string, integer, boolean, json
    
    -- Metadata
    description TEXT,
    is_system BOOLEAN DEFAULT FALSE,
    is_mutable BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_key (key)
);

-- ============================================================================
-- CREATE INDICES FOR PERFORMANCE
-- ============================================================================

-- Full-text search for audit logs
CREATE INDEX idx_audit_logs_fulltext ON audit_logs USING GIN(to_tsvector('english', action || ' ' || resource_type));

-- Full-text search for CVE descriptions
CREATE INDEX idx_cves_fulltext ON cves USING GIN(to_tsvector('english', title || ' ' || description));

-- Compression for large tables (if using TimescaleDB)
ALTER TABLE agent_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'agent_id'
);

SELECT add_compression_policy('agent_metrics', INTERVAL '30 days');
```

---

## VI. gRPC & Protocol Design

### 6.1 Service Definitions (protobuf)

**File:** `proto/agent.proto`
```protobuf
syntax = "proto3";

package lokilinux.agent;

option go_package = "github.com/lokilinux/lokilinux/proto/agent";
option java_package = "com.lokilinux.agent";

import "google/protobuf/timestamp.proto";
import "google/protobuf/duration.proto";
import "google/protobuf/struct.proto";

// ============================================================================
// AGENT REGISTRATION
// ============================================================================

service AgentService {
    rpc Register(RegisterRequest) returns (RegisterResponse);
    rpc Heartbeat(stream AgentHeartbeat) returns (stream HeartbeatResponse);
    rpc ExecuteJob(ExecuteJobRequest) returns (stream JobStatus);
    rpc ReportMetrics(stream MetricBatch) returns (MetricAck);
    rpc SyncPolicy(SyncPolicyRequest) returns (PolicyData);
    rpc InstallPlugin(PluginInstallRequest) returns (stream PluginInstallStatus);
}

message RegisterRequest {
    string agent_id = 1;
    string hostname = 2;
    SystemInfo system = 3;
    string cert_csr = 4;  // Certificate signing request
}

message RegisterResponse {
    string agent_id = 1;
    string agent_cert = 2;
    string ca_cert = 3;
    string heartbeat_interval_seconds = 4;
    bool success = 5;
    string error_message = 6;
}

// ============================================================================
// SYSTEM INFORMATION
// ============================================================================

message SystemInfo {
    string hostname = 1;
    string uname_all = 2;
    string os_family = 3;
    string os_distro = 4;
    string os_version = 5;
    string kernel_version = 6;
    string arch = 7;
    int32 cpu_count = 8;
    uint64 total_memory = 9;
    repeated Mount mounts = 10;
}

message Mount {
    string mount_point = 1;
    string filesystem = 2;
    uint64 total_size = 3;
    uint64 used_size = 4;
}

// ============================================================================
// HEARTBEAT & STATUS REPORTING
// ============================================================================

message AgentHeartbeat {
    string agent_id = 1;
    google.protobuf.Timestamp timestamp = 2;
    SystemInfo system = 3;
    repeated PackageInfo packages = 4;
    repeated string running_services = 5;
    google.protobuf.Struct custom_facts = 6;
    repeated CVEMatch vulnerabilities = 7;
    AgentHealth health = 8;
    repeated MetricPoint recent_metrics = 9;
    string agent_version = 10;
}

message PackageInfo {
    string name = 1;
    string version = 2;
    string architecture = 3;
    string repository = 4;
    string installed_at = 5;
    bool has_update = 6;
    string latest_version = 7;
    bool is_security_update = 8;
}

message CVEMatch {
    string cve_id = 1;
    string package_name = 2;
    float cvss_score = 3;
    string severity = 4;
    string fixed_version = 5;
    bool fix_available = 6;
}

message AgentHealth {
    enum Status {
        UNKNOWN = 0;
        HEALTHY = 1;
        DEGRADED = 2;
        UNHEALTHY = 3;
    }
    Status status = 1;
    float cpu_usage = 2;
    float memory_usage = 3;
    float disk_usage = 4;
    int32 connection_failures = 5;
    string last_error = 6;
}

message MetricPoint {
    google.protobuf.Timestamp timestamp = 1;
    string metric_name = 2;
    double value = 3;
    map<string, string> labels = 4;
}

message HeartbeatResponse {
    repeated Job pending_jobs = 1;
    PolicyData policy = 2;
    map<string, PluginAction> plugin_actions = 3;
    int32 next_heartbeat_interval = 4;
    string server_timestamp = 5;
}

// ============================================================================
// JOB EXECUTION
// ============================================================================

message ExecuteJobRequest {
    string job_id = 1;
    string job_type = 2;  // PACKAGE_UPDATE, SECURITY_PATCH, CVE_SCAN, CUSTOM_COMMAND, REMEDIATION
    map<string, string> parameters = 3;
    int32 timeout_seconds = 4;
    bool rollback_on_failure = 5;
}

message Job {
    string job_id = 1;
    string job_type = 2;
    map<string, string> parameters = 3;
    int32 timeout_seconds = 4;
    google.protobuf.Timestamp scheduled_time = 5;
}

message JobStatus {
    enum State {
        PENDING = 0;
        RUNNING = 1;
        COMPLETED = 2;
        FAILED = 3;
        TIMEOUT = 4;
        CANCELLED = 5;
    }
    string job_id = 1;
    State state = 2;
    string output = 3;
    int32 exit_code = 4;
    google.protobuf.Timestamp timestamp = 5;
    string error_message = 6;
}

// ============================================================================
// METRICS
// ============================================================================

message MetricBatch {
    string agent_id = 1;
    repeated MetricPoint metrics = 2;
    google.protobuf.Timestamp batch_timestamp = 3;
}

message MetricAck {
    bool success = 1;
    string error_message = 2;
}

// ============================================================================
// POLICY SYNCHRONIZATION
// ============================================================================

message SyncPolicyRequest {
    string agent_id = 1;
    string current_policy_version = 2;
}

message PolicyData {
    string policy_id = 1;
    string version = 2;
    google.protobuf.Struct rules = 3;
    repeated string command_whitelist = 4;
    int32 heartbeat_interval = 5;
    bool allow_plugins = 6;
    repeated string allowed_plugins = 7;
}

// ============================================================================
// PLUGIN MANAGEMENT
// ============================================================================

message PluginInstallRequest {
    string plugin_name = 1;
    string plugin_version = 2;
    string plugin_binary_url = 3;
    string plugin_signature = 4;
    google.protobuf.Struct config = 5;
}

message PluginInstallStatus {
    enum Phase {
        DOWNLOADING = 0;
        VERIFYING = 1;
        INSTALLING = 2;
        STARTING = 3;
        COMPLETED = 4;
        FAILED = 5;
    }
    string plugin_name = 1;
    Phase phase = 2;
    float progress_percent = 3;
    string error_message = 4;
}

message PluginAction {
    enum Action {
        INSTALL = 0;
        UPDATE = 1;
        UNINSTALL = 2;
        ENABLE = 3;
        DISABLE = 4;
    }
    Action action = 1;
    string plugin_name = 2;
    string plugin_version = 3;
    google.protobuf.Struct config = 4;
}

// ============================================================================
// CONTROL PLANE SERVICES
// ============================================================================

service PlatformService {
    rpc GetServerList(ServerListRequest) returns (ServerListResponse);
    rpc GetServerDetail(ServerDetailRequest) returns (ServerDetailResponse);
    rpc CreateJob(CreateJobRequest) returns (CreateJobResponse);
    rpc GetJobStatus(JobStatusRequest) returns (JobStatusResponse);
    rpc GetVulnerabilities(VulnerabilityRequest) returns (VulnerabilityResponse);
    rpc ApplyPolicy(ApplyPolicyRequest) returns (ApplyPolicyResponse);
}

message ServerListRequest {
    string filter_os = 1;
    repeated string filter_tags = 2;
    int32 limit = 3;
    int32 offset = 4;
}

message ServerListResponse {
    repeated ServerSummary servers = 1;
    int32 total_count = 2;
}

message ServerSummary {
    string agent_id = 1;
    string hostname = 2;
    string os_distro = 3;
    string status = 4;
    int32 vulnerability_count = 5;
    google.protobuf.Timestamp last_heartbeat = 6;
}

message ServerDetailRequest {
    string agent_id = 1;
}

message ServerDetailResponse {
    string agent_id = 1;
    string hostname = 2;
    SystemInfo system = 3;
    repeated PackageInfo packages = 4;
    AgentHealth health = 5;
    string current_policy_id = 6;
}

message CreateJobRequest {
    string job_type = 1;
    repeated string agent_ids = 2;
    map<string, string> parameters = 3;
    string policy_id = 4;
}

message CreateJobResponse {
    string job_id = 1;
    bool success = 2;
    string error_message = 3;
}

message JobStatusRequest {
    string job_id = 1;
}

message JobStatusResponse {
    string job_id = 1;
    string status = 2;
    repeated AgentJobResult results = 3;
}

message AgentJobResult {
    string agent_id = 1;
    string status = 2;
    string output = 3;
    int32 exit_code = 4;
}

message VulnerabilityRequest {
    string agent_id = 1;
    string severity_filter = 2;
    int32 limit = 3;
}

message VulnerabilityResponse {
    repeated CVEMatch vulnerabilities = 1;
}

message ApplyPolicyRequest {
    string policy_id = 1;
    repeated string agent_ids = 2;
}

message ApplyPolicyResponse {
    bool success = 1;
    int32 affected_agents = 2;
}
```

---

## VII. API ROUTES (FastAPI)

### 7.1 Authentication & Authorization

```python
# POST /api/v1/auth/login
# Login with username/password, return JWT

# POST /api/v1/auth/logout
# Invalidate JWT

# POST /api/v1/auth/mfa/enable
# Enable MFA for user

# POST /api/v1/auth/mfa/verify
# Verify MFA code

# POST /api/v1/auth/apikeys
# Create API key for integrations

# GET /api/v1/auth/user
# Get current user info
```

### 7.2 Servers/Agents

```python
# GET /api/v1/servers
# List all servers (with filters, pagination)
# Query: ?os=ubuntu&tags=production&status=active&limit=100&offset=0

# GET /api/v1/servers/{agent_id}
# Server detail

# PATCH /api/v1/servers/{agent_id}
# Update server metadata (tags, custom_facts)

# DELETE /api/v1/servers/{agent_id}
# Deregister agent

# GET /api/v1/servers/{agent_id}/packages
# List packages on server

# GET /api/v1/servers/{agent_id}/vulnerabilities
# List CVE-uri on server (with CVSS filters)

# GET /api/v1/servers/{agent_id}/metrics?range=7d
# Time-series metrics (CPU, RAM, disk, network)

# POST /api/v1/servers/{agent_id}/health-check
# Force health check/heartbeat

# POST /api/v1/servers/enroll-token
# Generate enrollment token (one-time)

# GET /api/v1/servers/health-summary
# Fleet health overview (total, healthy, unhealthy, offline)
```

### 7.3 Jobs

```python
# POST /api/v1/jobs
# Create new job
# Body: {job_type, target_servers, parameters, schedule}

# GET /api/v1/jobs
# List jobs (with filters, pagination)

# GET /api/v1/jobs/{job_id}
# Job detail + status

# GET /api/v1/jobs/{job_id}/results
# Job results per server

# POST /api/v1/jobs/{job_id}/cancel
# Cancel job (if still queued/pending)

# POST /api/v1/jobs/{job_id}/retry
# Retry failed job

# GET /api/v1/jobs/{job_id}/logs?agent_id=xxx
# Streaming logs from job execution
```

### 7.4 Packages & Updates

```python
# GET /api/v1/packages
# List all packages across fleet (aggregate view)

# GET /api/v1/packages/{package_name}
# Package detail (affected servers, available versions)

# GET /api/v1/packages/updates-available
# List all packages with available updates

# POST /api/v1/packages/batch-update
# Create batch update job for package(s)
# Body: {packages, target_servers, strategy: "immediate|staged|maintenance_window"}

# GET /api/v1/packages/update-history/{agent_id}
# Update history for server (APT/DNF history)
```

### 7.5 Vulnerabilities & CVE

```python
# GET /api/v1/vulnerabilities
# Global CVE dashboard
# Query: ?severity=critical&affected_servers>10&sort=cvss_desc

# GET /api/v1/vulnerabilities/{cve_id}
# CVE detail (affected packages, remediation)

# GET /api/v1/servers/{agent_id}/vulnerabilities
# CVE-uri on specific server

# POST /api/v1/vulnerabilities/{cve_id}/remediation-plan
# Generate auto-remediation plan
# Body: {strategy: "batch|staged|parallel", maintenance_window_id}

# POST /api/v1/vulnerabilities/{cve_id}/remediate
# Execute remediation (bulk update)

# GET /api/v1/vulnerabilities/trending
# CVE trends (new discoveries, critical escalations)

# POST /api/v1/vulnerabilities/update-feeds
# Force CVE database update (admin only)
```

### 7.6 Policies

```python
# POST /api/v1/policies
# Create policy
# Body: {name, policy_type, rules, target_servers}

# GET /api/v1/policies
# List policies

# GET /api/v1/policies/{policy_id}
# Policy detail

# PATCH /api/v1/policies/{policy_id}
# Update policy

# DELETE /api/v1/policies/{policy_id}
# Delete policy

# POST /api/v1/policies/{policy_id}/apply
# Apply policy to servers
# Body: {server_ids or filters}

# GET /api/v1/policies/{policy_id}/preview
# Preview which servers will match policy

# POST /api/v1/policies/{policy_id}/rollback
# Rollback to previous version

# GET /api/v1/policies/audit
# Policy change audit log
```

### 7.7 Plugins

```python
# GET /api/v1/plugins
# List installed plugins

# GET /api/v1/plugins/marketplace
# Browse plugin marketplace

# POST /api/v1/plugins/install
# Install plugin
# Body: {plugin_name, version, config}

# PATCH /api/v1/plugins/{plugin_id}
# Update plugin config

# DELETE /api/v1/plugins/{plugin_id}
# Uninstall plugin

# POST /api/v1/plugins/{plugin_id}/enable
# Enable plugin

# POST /api/v1/plugins/{plugin_id}/disable
# Disable plugin

# GET /api/v1/plugins/{plugin_id}/status
# Plugin health/status

# GET /api/v1/plugins/marketplace/search?q=docker&category=integration
# Search marketplace
```

### 7.8 Alerts

```python
# GET /api/v1/alerts
# List active alerts

# GET /api/v1/alerts/{alert_id}
# Alert detail

# POST /api/v1/alerts/{alert_id}/acknowledge
# Acknowledge alert

# POST /api/v1/alerts/{alert_id}/resolve
# Resolve alert

# GET /api/v1/alert-rules
# List alert rules

# POST /api/v1/alert-rules
# Create alert rule

# PATCH /api/v1/alert-rules/{rule_id}
# Update alert rule

# DELETE /api/v1/alert-rules/{rule_id}
# Delete alert rule
```

### 7.9 Audit & Compliance

```python
# GET /api/v1/audit/logs
# Audit log viewer (time-range, resource, action filters)

# GET /api/v1/compliance/overview
# Compliance dashboard (policy drift, remediation status)

# GET /api/v1/compliance/policy/{policy_id}
# Compliance report for specific policy

# POST /api/v1/compliance/export
# Export compliance report (PDF, JSON)
```

### 7.10 Admin

```python
# POST /api/v1/admin/users
# Create user

# GET /api/v1/admin/users
# List users

# PATCH /api/v1/admin/users/{user_id}
# Update user (name, role, email)

# DELETE /api/v1/admin/users/{user_id}
# Delete user

# POST /api/v1/admin/roles
# Create custom role

# GET /api/v1/admin/roles
# List roles

# PATCH /api/v1/admin/roles/{role_id}
# Update role (permissions)

# GET /api/v1/admin/settings
# System settings

# PATCH /api/v1/admin/settings
# Update settings (CVE feed frequency, retention, etc.)

# POST /api/v1/admin/backup
# Trigger backup

# POST /api/v1/admin/restore
# Restore from backup

# GET /api/v1/admin/system-health
# System health (DB, queue, external services)
```

---

## VIII. DEPLOYMENT ARCHITECTURE

### 8.1 Single-Node Development Deployment

```yaml
# docker-compose.yml
version: "3.9"

services:
  # Database
  postgres:
    image: postgres:15-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: lokilinux
      POSTGRES_USER: lokilinux
      POSTGRES_PASSWORD: dev_password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # Event Bus
  nats:
    image: nats:2.10
    ports:
      - "4222:4222"
      - "6222:6222"
      - "8222:8222"

  # Metrics Database
  timescaledb:
    image: timescale/timescaledb:latest-pg15
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: metrics
      POSTGRES_USER: metrics
      POSTGRES_PASSWORD: dev_password
    volumes:
      - timescaledb_data:/var/lib/postgresql/data

  # Cache
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # API & Backend Services
  lokilinux-api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
      - "50051:50051"  # gRPC
    environment:
      DATABASE_URL: "postgresql://lokilinux:dev_password@postgres:5432/lokilinux"
      METRICS_DATABASE_URL: "postgresql://metrics:dev_password@timescaledb:5432/metrics"
      NATS_URL: "nats://nats:4222"
      REDIS_URL: "redis://redis:6379"
      ENVIRONMENT: "development"
    depends_on:
      - postgres
      - timescaledb
      - nats
      - redis
    volumes:
      - ./backend:/app

  # Frontend
  lokilinux-web:
    build:
      context: ./frontend
      dockerfile: Dockerfile.dev
    ports:
      - "3000:3000"
    environment:
      VITE_API_URL: "http://localhost:8000"
      VITE_GRPC_URL: "localhost:50051"
    depends_on:
      - lokilinux-api
    volumes:
      - ./frontend:/app

volumes:
  postgres_data:
  timescaledb_data:
```

### 8.2 Kubernetes HA Deployment

```yaml
# kubernetes/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: lokilinux

---
# kubernetes/postgres-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: lokilinux
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:15-alpine
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: lokilinux
        - name: POSTGRES_USER
          value: lokilinux
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pg_isready -U lokilinux
          initialDelaySeconds: 30
          periodSeconds: 10
  volumeClaimTemplates:
  - metadata:
      name: postgres-storage
    spec:
      accessModes: [ "ReadWriteOnce" ]
      resources:
        requests:
          storage: 100Gi

---
# kubernetes/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: lokilinux-api
  namespace: lokilinux
spec:
  replicas: 3
  selector:
    matchLabels:
      app: lokilinux-api
  template:
    metadata:
      labels:
        app: lokilinux-api
    spec:
      containers:
      - name: api
        image: lokilinux/api:latest
        ports:
        - containerPort: 8000
          name: http
        - containerPort: 50051
          name: grpc
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: connection-string
        - name: NATS_URL
          value: "nats://nats-cluster:4222"
        - name: REDIS_URL
          value: "redis://redis-master:6379"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"

---
# kubernetes/api-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: lokilinux-api
  namespace: lokilinux
spec:
  type: LoadBalancer
  ports:
  - port: 443
    targetPort: 8000
    protocol: TCP
    name: https
  - port: 50051
    targetPort: 50051
    protocol: TCP
    name: grpc
  selector:
    app: lokilinux-api
```

---

## IX. SECURITY ARCHITECTURE

### 9.1 Authentication & Authorization

**mTLS Agent Auth:**
- Each agent gets unique certificate during enrollment
- Certificates signed by CA, valid for 1 year
- Certificate renewal (30 days before expiry)
- Revocation list (CRL) checked on heartbeat

**User Authentication:**
- Local: username/password + bcrypt
- LDAP: optional integration for enterprise
- OAuth2: support for SSO (Keycloak, Azure AD)
- MFA: TOTP (Google Authenticator, Authy)

**Authorization:**
- RBAC: roles define set of permissions
- Resource-based access: can limit access to specific servers/groups
- Audit all authorization decisions

### 9.2 Data Protection

**In Transit:**
- All APIs: TLS 1.2+ enforced
- gRPC: mTLS + TLS 1.2+
- Agent communication: mTLS required

**At Rest:**
- Database: encryption at filesystem level (LUKS, EBS encryption)
- Sensitive fields: encrypted in DB (API keys, CVE feed tokens, plugin configs)
- Backups: encrypted, stored offline

**Password & Secret Management:**
- Use bcrypt for password hashing (cost factor 12)
- API keys: salted+hashed before storage
- Secret rotation: support for key rotation on schedule
- Integration with HashiCorp Vault (optional plugin)

### 9.3 API Security

**Rate Limiting:**
- Per-user: 1000 req/min
- Per-IP: 10000 req/min
- Per-endpoint: dynamic limits

**Input Validation:**
- All inputs validated (Pydantic schema validation)
- SQL injection protection (parameterized queries)
- XSS protection (output encoding)
- CSRF tokens for state-changing operations

**CORS:**
- Strict CORS configuration (whitelisted origins)
- SameSite cookies: Strict

### 9.4 Privilege Escalation Prevention

**Agent Sandbox:**
- Commands run in forked process (separate PID namespace)
- ulimit resource constraints
- seccomp filter restricts syscalls
- No shell access

**Plugin Isolation:**
- Plugins run in separate process (separate namespace)
- cgroup resource limits per plugin
- Sandbox filesystem (if possible)
- No access to host filesystem unless explicitly allowed

**Audit Logging:**
- Log all privilege-requiring actions
- Log job execution (command, output, user, timestamp)
- Retention: 2 years

---

## X. SCALING STRATEGY

### 10.1 Horizontal Scaling

**Database Tier:**
- PostgreSQL replication: streaming replication to standby
- Read replicas for reporting
- Connection pooling (pgBouncer): 1000 connections max
- Query optimization: indexes on frequently filtered columns

**API Tier:**
- Stateless API instances (load balancer: NGINX, HAProxy, AWS ALB)
- Horizontal auto-scaling (K8s HPA, AWS ASG)
- Target: <70% CPU, <80% memory
- Min 3 replicas, max 10 replicas

**gRPC Tier:**
- Separate load balancer for gRPC (L7 aware)
- Connection pooling on agent side
- Keepalive pings every 30s

**Worker Tier:**
- Async job workers (consume from NATS queue)
- Auto-scale based on queue depth
- Each worker handles 10 concurrent jobs
- Target: 5K servers = 10-20 workers

**Event Bus (NATS):**
- Cluster mode: 3+ NATS nodes
- Persistence: Jetstream (event log)
- Replication factor: 3
- Retention: 24h

**Cache (Redis):**
- Redis Sentinel or Cluster mode for HA
- Persistence: AOF snapshots
- Eviction policy: allkeys-lru

### 10.2 Time-Series Data

**TimescaleDB:**
- Compression: after 30 days (columnar storage)
- Retention: 365 days (older data deleted)
- Data aggregation: 1-min → 5-min → hourly rollup

**Archival:**
- Old data: export to S3 (Parquet format)
- Query: use Athena for historical analysis

### 10.3 Cost Optimization

**Compute:**
- Use spot instances (AWS) for workers (30% cost savings)
- Right-size instances (m6i.xlarge, not m6i.2xlarge)
- Reserved instances for API tier (40% discount)

**Storage:**
- Compress old audit logs (gzip, 70% reduction)
- Tiered storage: hot (SSD) → warm (HDD) → cold (S3 Glacier)

**Network:**
- Compression on agent → API communication
- Delta synchronization (only changed data)
- Batch operations (combine multiple heartbeats)

---

## XI. DISASTER RECOVERY & BACKUP

### 11.1 Backup Strategy

**Database:**
- Automated daily snapshots (pg_basebackup)
- Retention: 30 days
- Location: AWS S3, encrypted
- Test restore monthly

**Configuration:**
- Git-based config (policies, plugin configs)
- Auto-commit changes with audit trail

**Certificates & Keys:**
- Encrypted backup (AES-256)
- Stored offline (HSM or vault)
- Retention: 2 years

### 11.2 Recovery Time Objectives (RTO)

| Component | RTO | RPO |
|---|---|---|
| API | 1h | 5 min |
| Database | 4h | 1 min |
| Agent certificates | 24h | none (can re-enroll) |
| Plugin registry | 4h | 1h |

---

## XII. OBSERVABILITY

### 12.1 Logging

**Structured Logging (JSON):**
```json
{
  "timestamp": "2026-06-26T10:30:00Z",
  "level": "ERROR",
  "service": "job-engine",
  "job_id": "abc123",
  "agent_id": "xyz789",
  "message": "Job execution failed",
  "error": "package not found",
  "trace_id": "xxxxxx",
  "span_id": "yyyyy"
}
```

**Log Aggregation:**
- ELK Stack (Elasticsearch, Logstash, Kibana) or
- Grafana Loki (lighter-weight)
- Retention: 30 days for API, 7 days for agent

### 12.2 Metrics

**Prometheus-compatible metrics:**
```
# API metrics
lokilinux_api_requests_total{method="POST", endpoint="/jobs", status="200"}
lokilinux_api_request_duration_seconds{quantile="0.95"}
lokilinux_api_db_connections{pool="main"}

# Agent metrics
lokilinux_agent_heartbeat_latency_ms
lokilinux_agent_job_duration_seconds
lokilinux_agent_memory_usage_bytes
lokilinux_agent_cache_hit_ratio

# Business metrics
lokilinux_servers_total{status="active"}
lokilinux_cves_critical{severity="critical"}
lokilinux_jobs_completed_total
```

**Grafana Dashboards:**
- Fleet overview (servers, health, CVE trends)
- API performance (req/s, latency, errors)
- Agent health (heartbeat latency, offline count)
- CVE trends (new discoveries, remediation progress)
- Job execution (success rate, duration distribution)

### 12.3 Distributed Tracing

**OpenTelemetry:**
- Trace all API requests end-to-end
- Correlate with job execution on agents
- Export to Jaeger or Grafana Tempo
- Sample rate: 10% in production

---

## XIII. TESTING STRATEGY

### 13.1 Unit Tests

**Agent:**
```bash
# Go tests for agent modules
go test ./pkg/agent/... -v -race -cover
# Coverage target: >80%
```

**Backend:**
```bash
# Python tests for API/services
pytest tests/unit/ -v --cov=lokilinux
# Coverage target: >85%
```

**Frontend:**
```bash
# Vue/TypeScript tests
vitest run --coverage
# Coverage target: >75%
```

### 13.2 Integration Tests

- Test agent ↔ API communication
- Test job execution end-to-end
- Test database transactions
- Test event bus pub/sub

### 13.3 Load Tests

- Simulate 10K agents sending heartbeats
- Simulate 1K concurrent job executions
- Measure latency (p95, p99)
- Target: <100ms API response, <1s job scheduling

### 13.4 Security Tests

- Penetration testing (annual)
- SAST scan (every commit, Semgrep)
- DAST scan (weekly, OWASP ZAP)
- Dependency vulnerability scan (continuous, Snyk)

---

## XIV. REPOSITORY STRUCTURE

```
lokilinux/
├── README.md
├── LICENSE
├── ARCHITECTURE.md
├── CONTRIBUTING.md
│
├── backend/
│   ├── pyproject.toml
│   ├── poetry.lock
│   ├── Dockerfile
│   ├── .env.example
│   ├── alembic/                    # Database migrations
│   │   ├── versions/
│   │   ├── env.py
│   │   └── script.py.mako
│   ├── lokilinux/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app entry
│   │   ├── config.py               # Configuration management
│   │   ├── models/
│   │   │   ├── agent.py
│   │   │   ├── job.py
│   │   │   ├── cve.py
│   │   │   ├── policy.py
│   │   │   └── ...
│   │   ├── schemas/                # Pydantic schemas (API input/output)
│   │   │   ├── agent.py
│   │   │   ├── job.py
│   │   │   └── ...
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── v1/
│   │   │   │   ├── routers/
│   │   │   │   │   ├── agents.py
│   │   │   │   │   ├── jobs.py
│   │   │   │   │   ├── vulnerabilities.py
│   │   │   │   │   ├── policies.py
│   │   │   │   │   ├── plugins.py
│   │   │   │   │   └── ...
│   │   │   │   ├── dependencies.py
│   │   │   │   └── api.py          # API router aggregator
│   │   │   └── grpc/               # gRPC services
│   │   │       ├── agent_service.py
│   │   │       └── platform_service.py
│   │   ├── services/
│   │   │   ├── agent_service.py
│   │   │   ├── job_service.py
│   │   │   ├── cve_service.py
│   │   │   ├── inventory_service.py
│   │   │   ├── policy_service.py
│   │   │   ├── plugin_service.py
│   │   │   ├── alert_service.py
│   │   │   ├── auth_service.py
│   │   │   └── audit_service.py
│   │   ├── workers/                # Async job workers
│   │   │   ├── job_executor.py
│   │   │   ├── cve_processor.py
│   │   │   └── event_handlers.py
│   │   ├── integrations/           # External integrations
│   │   │   ├── zabbix/
│   │   │   ├── prometheus/
│   │   │   └── ldap/
│   │   ├── utils/
│   │   │   ├── crypto.py           # Encryption, cert generation
│   │   │   ├── validators.py
│   │   │   └── helpers.py
│   │   └── db/
│   │       ├── base.py
│   │       ├── session.py
│   │       └── cache.py
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       ├── integration/
│       └── load/
│
├── agent/                          # Go agent
│   ├── go.mod
│   ├── go.sum
│   ├── main.go
│   ├── Makefile                    # Build for multiple platforms
│   ├── Dockerfile
│   ├── packaging/
│   │   ├── debian/
│   │   │   └── lokilinux-agent.deb.control
│   │   └── rpm/
│   │       └── lokilinux-agent.spec
│   ├── pkg/
│   │   ├── config/
│   │   ├── agent/
│   │   │   ├── manager.go           # Agent main loop
│   │   │   ├── heartbeat.go
│   │   │   └── cache.go
│   │   ├── modules/
│   │   │   ├── system_info.go
│   │   │   ├── package_manager.go
│   │   │   ├── vulnerability.go
│   │   │   ├── metrics.go
│   │   │   └── job_executor.go
│   │   ├── communication/
│   │   │   ├── grpc_client.go
│   │   │   ├── protocol.go
│   │   │   └── mtls.go
│   │   ├── plugins/
│   │   │   ├── loader.go
│   │   │   ├── sandbox.go
│   │   │   └── ipc.go
│   │   └── utils/
│   │       ├── logging.go
│   │       └── crypto.go
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── fixtures/
│
├── frontend/
│   ├── package.json
│   ├── nuxt.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── Dockerfile
│   ├── .env.example
│   ├── app.vue
│   ├── app.config.ts
│   ├── pages/
│   │   ├── index.vue               # Dashboard
│   │   ├── servers/
│   │   │   ├── index.vue
│   │   │   └── [id]/
│   │   │       ├── index.vue
│   │   │       ├── packages.vue
│   │   │       ├── vulnerabilities.vue
│   │   │       └── ...
│   │   ├── jobs/
│   │   ├── vulnerabilities/
│   │   ├── policies/
│   │   ├── plugins/
│   │   ├── alerts/
│   │   ├── audit/
│   │   └── admin/
│   ├── components/
│   │   ├── ServerCard.vue
│   │   ├── CVECardboard.vue
│   │   ├── JobProgress.vue
│   │   └── ...
│   ├── composables/
│   │   ├── useAuth.ts
│   │   ├── useServers.ts
│   │   ├── useJobs.ts
│   │   └── ...
│   ├── stores/
│   │   ├── auth.ts
│   │   ├── servers.ts
│   │   ├── jobs.ts
│   │   └── ...
│   ├── types/
│   │   ├── api.ts
│   │   ├── server.ts
│   │   ├── job.ts
│   │   └── ...
│   ├── utils/
│   │   ├── api.ts
│   │   ├── formatting.ts
│   │   └── ...
│   └── tests/
│       ├── unit/
│       └── e2e/
│
├── proto/                          # Protocol Buffers
│   ├── agent.proto
│   ├── platform.proto
│   └── common.proto
│
├── kubernetes/                     # K8s manifests
│   ├── namespace.yaml
│   ├── postgres/
│   │   ├── statefulset.yaml
│   │   └── service.yaml
│   ├── nats/
│   ├── redis/
│   ├── api/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── configmap.yaml
│   │   └── secrets.yaml
│   ├── ingress.yaml
│   └── hpa.yaml
│
├── docker-compose.yml              # Development environment
├── docker-compose.prod.yml         # Production-like environment
│
├── scripts/
│   ├── install-agent.sh            # Agent installation script
│   ├── enroll-agent.sh
│   ├── generate-certs.sh
│   ├── migrate-db.sh
│   └── backup.sh
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── agent-development.md
│   ├── plugin-development.md
│   ├── deployment.md
│   ├── scaling.md
│   └── security.md
│
├── .github/
│   └── workflows/
│       ├── ci-backend.yml
│       ├── ci-agent.yml
│       ├── ci-frontend.yml
│       ├── security-scan.yml
│       └── release.yml
│
└── .gitignore
```

---

## XV. MVP ROADMAP (Phase 1 — 6 Months)

### M1-2: Core Platform
- [ ] PostgreSQL + NATS + Redis infrastructure
- [ ] FastAPI base + API Gateway
- [ ] Basic auth (local users, JWT)
- [ ] Agent skeleton (Go, basic heartbeat)
- [ ] Nuxt frontend skeleton

### M2-3: Agent Features
- [ ] System info collection
- [ ] Package manager integration (apt, dnf)
- [ ] Job execution engine (package update, custom commands)
- [ ] Local caching & offline mode
- [ ] Metrics collection

### M3-4: Platform Services
- [ ] Inventory service + list/search
- [ ] Job service + job queue
- [ ] Basic CVE database + matching
- [ ] Agent health monitoring
- [ ] Audit logging

### M4-5: Frontend & UI
- [ ] Server list/detail pages
- [ ] Job creation + monitoring
- [ ] Vulnerability dashboard
- [ ] Metrics visualization

### M5-6: Security & Polish
- [ ] mTLS agent auth
- [ ] RBAC implementation
- [ ] Alert system (basic)
- [ ] Plugin marketplace skeleton
- [ ] Deployment docs + K8s manifests

**MVP Output:**
- 10K servers support
- Update + remediation workflows
- Web UI for fleet management
- REST API + gRPC
- Kubernetes deployment

---

## XVI. ENTERPRISE ROADMAP (Phase 2-3 — 12 Months)

### Enterprise Features
- [ ] Advanced policy engine (CEL DSL)
- [ ] Compliance automation (CIS benchmarks, STIG)
- [ ] Multi-tenancy (RBAC per org)
- [ ] Advanced analytics (ML anomaly detection)
- [ ] Disaster recovery (active-active)
- [ ] Cost optimization module
- [ ] Custom plugin development SDK
- [ ] Marketplace with 50+ plugins

### Integrations
- [ ] Zabbix connector
- [ ] Prometheus scraper
- [ ] Grafana datasource
- [ ] ServiceNow/Jira sync
- [ ] CrowdSec integration
- [ ] Vault integration

### Scale Targets
- [ ] 100K+ servers
- [ ] Multi-region deployment
- [ ] Edge agent support (IoT)
- [ ] Federated management (hub-spoke)

---

## XVII. THREAT MODEL

**Assets:**
- Inventory data (server list, package versions)
- CVE database (security-sensitive)
- Job execution history (audit trail)
- User credentials & API keys
- Agent certificates

**Threats:**

| Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Agent compromise | Low | Critical | Sandbox, seccomp, secure boot |
| API injection | Medium | High | Input validation, parameterized queries |
| Certificate theft | Low | Critical | mTLS, certificate pinning, HSM |
| Unauthorized job execution | Medium | Critical | RBAC, audit logging, approval workflow |
| Data exfiltration | Low | High | Encryption in transit + at rest |
| DoS on API | Medium | Medium | Rate limiting, DDoS protection |

---

## XVIII. PERFORMANCE TARGETS

| Metric | Target |
|---|---|
| Agent heartbeat latency | <100ms (p95) |
| Job scheduling latency | <1s |
| Vulnerability scan latency | <30s (per server) |
| API response (avg) | <200ms |
| API response (p99) | <1000ms |
| CVE database sync | <5 min |
| Bulk job creation | >100 jobs/sec |
| Agents per instance | 100-10K (depending on spec) |
| Memory footprint (agent) | <50 MB |
| CPU footprint (agent idle) | <1% |

---

## XIX. BEST PRACTICES & STANDARDS

### Code Quality
- Linting: pylint, flake8 (Python), golangci-lint (Go), ESLint (JS)
- Formatting: black (Python), gofmt (Go), prettier (JS)
- Type checking: mypy (Python), TypeScript (JS)
- Testing: pytest (Python), go test (Go), vitest (JS)

### API Design
- REST: JSON, snake_case, semantic HTTP codes
- gRPC: protobuf v3, streaming for long-running ops
- Versioning: URL-based (/api/v1/, /api/v2/)
- Docs: OpenAPI/Swagger for REST

### Database
- ACID transactions
- Connection pooling
- Query optimization (explain analyze)
- Backup: WAL-archived, point-in-time recovery

### Deployment
- Immutable containers (Docker)
- Infrastructure as code (Terraform)
- Secrets management (Vault, sealed secrets)
- Git-based deployment (GitOps)

---

## XX. RECOMMENDED TIMELINE & EFFORT

| Phase | Duration | Team Size | Deliverable |
|---|---|---|---|
| MVP (Phase 1) | 6 months | 8-10 eng | Core platform, 10K server support |
| Beta | 3 months | 6-8 eng | Polish, integrations, 50K server support |
| GA | 2 months | 5-6 eng | Enterprise features, 100K+ support |
| **Total** | **~12 months** | **5-10 eng** | **Production-ready platform** |

---

## CONCLUSION

LokiLinux adalah platform enterprise-grade untuk management Linux fleet dengan fokus pe vulnerabilități, patch management, și compliance automation. Arhitectura este diseñada pentru scalability, security, și operational excellence.

**Key Success Factors:**
1. Lightweight agent (no Python/Node runtime)
2. Event-driven architecture (NATS)
3. Modular plugin system (extensible)
4. Strong security model (mTLS, RBAC, audit)
5. Operational excellence (observability, HA, DR)

Implementarea trebuie să urmeze best practices Cloud-Native și Enterprise Linux management standards.
