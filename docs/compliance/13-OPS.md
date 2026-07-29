<!-- generated-by: claude -->
# Scaling, Security, Deployment, Roadmap

## 1. Scaling strategy — designed for 100,000+ servers

| Concern | Mechanism |
|---|---|
| Heartbeat traffic | Per-domain delta sync (D2) — only changed domains' full bodies cross the wire; unchanged domains cost one hash string |
| Snapshot storage | Content-addressable blobs (D3) — a golden-image fleet of 50,000 hosts costs one blob per domain, not 50,000 |
| Ingest throughput | `lokilinux-compliance` horizontally scaled via NATS JetStream queue groups; each replica runs a bounded worker pool, not one goroutine per message |
| Hot tables | `rule_evaluations`, `drift_events`, `inventory_deltas`, `compliance_scores`, `file_changes` are all TimescaleDB hypertables, space-partitioned on `agent_id` (16 partitions) in addition to time, so a single hot agent can't skew one chunk |
| Query cost on trend charts | Continuous aggregates (`compliance_scores_daily`) — dashboard trend widgets never scan raw rows |
| Rule evaluation cost | CEL programs compiled once per `rule.ID` and cached (`internal/rules/engine.go`), not recompiled per agent per evaluation |
| Scheduler contention | Single elected leader (NATS KV) runs cron/sweep logic; ingest scales independently of leadership |
| Retention | Compression policies at 7-30 days, hard retention 90 days-2 years per table (§ [01-DATA-MODEL.md](01-DATA-MODEL.md)), Parquet archive before drop |
| Millions of drift events | Hypertable + compression + retention is the same recipe already proven at 10K-100K scale by the existing `agent_metrics` hypertable (`migration 001`) — this module doesn't invent a new scaling approach, it reuses the one already in production |

Capacity model: at 100,000 agents × 60s heartbeat × ~25 domains, assuming delta-sync reduces
full-body sends to ~2% of domains per beat (most configs are static day-to-day), sustained
full-snapshot ingest is on the order of ~800/sec fleet-wide — well within a few
`lokilinux-compliance` replicas each running a `NumCPU()*4`-sized worker pool.

## 2. Security architecture

- **Transport**: agent↔control-plane already mTLS (existing `certs/` CA); no new agent port
  opened by this module (D1) — snapshots ride the existing heartbeat stream.
- **AuthN/Z**: every new `/api/v1/compliance/*` endpoint uses the existing `get_current_user`/
  `require_role` dependencies — no parallel auth system. `AUDITOR` gets read access fleet-wide
  in this module by design (it's the role that exists to read compliance/audit state).
- **Signed baselines**: Ed25519 signing on publish ([06-BASELINE.md](06-BASELINE.md) §3),
  private key mounted only into `lokilinux-compliance`, never into the API or frontend
  container — tamper detection without expanding the key's blast radius if any other
  container is compromised.
- **Signed policy content**: `remediation_templates` imported from ComplianceAsCode carry
  `source_version` (pinned upstream release tag); the importer verifies the upstream repo's
  git tag signature before import, so a compromised upstream mirror can't inject unsigned
  remediation scripts silently.
- **Tamper detection on file integrity**: FIM hashes are themselves protected by the same
  content-addressable, append-only `inventory_deltas`/`file_changes` hypertables — no UPDATE
  path exists on historical rows, so a compromised operator account can acknowledge/annotate
  but never rewrite what was actually observed.
- **Secrets**: `ai.api_key` and any provider credentials stored via the same encrypted-setting
  treatment already used for `security.ldap_bind_password` — never logged, never included in
  `ai_recommendations.prompt_context` or RAG-retrievable documents.
- **RBAC fine-grained enough for the brief's requirement**: mutation endpoints gated per-action
  (`baseline.approve` needs `ADMIN`; `baseline.submit` needs `ADMIN`/`OPERATOR`), not just
  per-resource — matches the existing `require_role(*roles)` dependency-factory pattern, which
  already supports arbitrary per-endpoint role sets without new RBAC infrastructure.
- **Approval workflow as a security control, not just a UX step**: no path exists from AI
  proposal or automatic scan finding to executed remediation without a human `approve` call
  recorded in `audit_logs` (§ [10-AI.md](10-AI.md) §3, [09-REMEDIATION.md](09-REMEDIATION.md) §7).

## 3. Deployment architecture

### docker-compose addition

```yaml
  # ============================================================================
  # COMPLIANCE — Go microservice (drift/policy/scoring engine), no public port
  # ============================================================================
  lokilinux-compliance:
    build:
      context: ./services/compliance
      dockerfile: Dockerfile
    image: lokilinux/compliance:${LOKILINUX_VERSION:-latest}
    container_name: lokilinux-compliance
    restart: unless-stopped
    depends_on:
      pgbouncer:
        condition: service_healthy
      nats:
        condition: service_healthy
      lokilinux-migrate:
        condition: service_completed_successfully
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@pgbouncer:5432/${POSTGRES_DB}
      NATS_URL: nats://nats:4222
      LOG_LEVEL: ${LOG_LEVEL:-info}
    volumes:
      - certs_dir:/etc/lokilinux/certs:ro
    networks:
      - lokilinux-network
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://127.0.0.1:8080/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    deploy:
      # Single instance here, matching every other service in this compose file
      # (container_name is fixed, incompatible with deploy.replicas > 1). Real
      # horizontal scaling — multiple replicas, one elected scheduler leader via
      # NATS KV — is a Kubernetes-deployment concern; see the HPA manifest below.
      resources:
        limits:
          cpus: "2"
          memory: 2G
```

Same build-context/image/healthcheck/resource-limit shape as every other service in the
existing `docker-compose.yml` — no new deployment pattern introduced.

### Kubernetes (roadmap target, once past docker-compose-only deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: lokilinux-compliance
spec:
  replicas: 4
  selector: { matchLabels: { app: lokilinux-compliance } }
  template:
    metadata: { labels: { app: lokilinux-compliance } }
    spec:
      containers:
        - name: compliance
          image: lokilinux/compliance:latest
          ports: [{ containerPort: 9091, name: metrics }]
          readinessProbe: { httpGet: { path: /healthz, port: 8080 } }
          resources:
            requests: { cpu: "500m", memory: "512Mi" }
            limits: { cpu: "2", memory: "2Gi" }
          volumeMounts:
            - { name: certs, mountPath: /etc/lokilinux/certs, readOnly: true }
      volumes:
        - name: certs
          secret: { secretName: lokilinux-certs }
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: lokilinux-compliance }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: lokilinux-compliance }
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Pods
      pods:
        metric: { name: nats_jetstream_consumer_pending }
        target: { type: AverageValue, averageValue: "500" }
```

## 4. Future roadmap

| Phase | Scope |
|---|---|
| Phase 0 (prerequisite) | Job→agent wire fix, `policy.apply` subscriber, `AuditService` everywhere ([00-OVERVIEW.md](00-OVERVIEW.md) §6) |
| Phase 1 | Inventory Collector + delta sync + content-addressable storage; Baseline Manager CRUD + scope resolution; Compliance Dashboard read-only views |
| Phase 2 | Policy Engine + ComplianceAsCode importer + CEL evaluation; Drift Detection; Historical Audit wiring |
| Phase 3 | Remediation Engine (Ansible/shell providers) + maintenance windows; File Integrity Monitoring |
| Phase 4 | AI Compliance Assistant (RAG + planner + Tool API) |
| Phase 5 | Reporting Engine (PDF/CSV/XLSX export); Kubernetes deployment manifests; `OSCAP_FALLBACK` provider for orgs needing full OVAL fidelity |
| Future (not scoped, not speculatively designed) | Terraform remediation provider (once a real infra-drift use case exists); agent-local baseline enforcement (today server-side detection only); Python remediation executor promoted from "planned" to built once a real use case needs it over shell/Ansible |

## 5. Coverage — every requested output, mapped

| # | Brief output | Covered by |
|---|---|---|
| 1 | Complete software architecture | [00-OVERVIEW.md](00-OVERVIEW.md) |
| 2 | Microservice architecture | [00-OVERVIEW.md](00-OVERVIEW.md) §5 D1, [02-GO-SERVICE.md](02-GO-SERVICE.md) |
| 3 | Database schema | [01-DATA-MODEL.md](01-DATA-MODEL.md) |
| 4 | Go package structure | [02-GO-SERVICE.md](02-GO-SERVICE.md) §2 |
| 5 | Agent plugin structure | [03-AGENT-PLUGIN-SDK.md](03-AGENT-PLUGIN-SDK.md) |
| 6 | API specification | [05-API.md](05-API.md) |
| 7 | Frontend page structure | [11-FRONTEND.md](11-FRONTEND.md) §1 |
| 8 | Workflow diagrams | [12-DIAGRAMS.md](12-DIAGRAMS.md) §1 |
| 9 | Sequence diagrams | [12-DIAGRAMS.md](12-DIAGRAMS.md) §2-4 |
| 10 | Remediation workflow | [09-REMEDIATION.md](09-REMEDIATION.md) §2 |
| 11 | AI architecture | [10-AI.md](10-AI.md) |
| 12 | RAG architecture | [10-AI.md](10-AI.md) §2 |
| 13 | Scheduler architecture | [02-GO-SERVICE.md](02-GO-SERVICE.md) §4 |
| 14 | Job integration | [09-REMEDIATION.md](09-REMEDIATION.md) §1, §7 |
| 15 | Plugin SDK | [03-AGENT-PLUGIN-SDK.md](03-AGENT-PLUGIN-SDK.md) §1-2 |
| 16 | Example Go interfaces | [02-GO-SERVICE.md](02-GO-SERVICE.md) §3, [03-AGENT-PLUGIN-SDK.md](03-AGENT-PLUGIN-SDK.md) §2 |
| 17 | Example protobuf definitions | [04-PROTOCOL.md](04-PROTOCOL.md) |
| 18 | Example REST endpoints | [05-API.md](05-API.md) |
| 19 | Example PostgreSQL schema | [01-DATA-MODEL.md](01-DATA-MODEL.md) |
| 20 | Example React pages | [11-FRONTEND.md](11-FRONTEND.md) (Vue/Nuxt — premise-corrected, §0 and [00-OVERVIEW.md](00-OVERVIEW.md) §2) |
| 21 | Ansible integration architecture | [09-REMEDIATION.md](09-REMEDIATION.md) §3, §6 |
| 22 | Historical audit architecture | [12-DIAGRAMS.md](12-DIAGRAMS.md) §5, [01-DATA-MODEL.md](01-DATA-MODEL.md) §9 |
| 23 | Scaling strategy | this document §1 |
| 24 | Security architecture | this document §2 |
| 25 | Deployment architecture | this document §3 |
| 26 | Future roadmap | this document §4 |

Every numbered requirement in the original brief is addressed above; where the brief's assumed
technology (Go/Fiber backend, React frontend) didn't match the actual repository, the
corresponding document explains the correction inline rather than silently substituting one
stack for another.
