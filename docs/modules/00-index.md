# LokiLinux — Index documentație module

> Documentație generată din cod la commit `77c4220` (v0.3.0), august 2026.

LokiLinux este o platformă enterprise de operațiuni pentru infrastructură Linux: managementul flotelor, patch management centralizat, scanare vulnerabilități, compliance & drift management și remediere automată, dimensionată pentru 10K–100K+ servere.

## Modulele aplicației

| Document | Modul | Tehnologie | Rol într-o frază |
|---|---|---|---|
| [01-frontend.md](01-frontend.md) | Frontend | Nuxt 4 + Vue 3 + Pinia + Better Auth | UI complet: dashboard, flota, compliance, workflow builder; furnizorul de identitate |
| [02-control-plane.md](02-control-plane.md) | Control Plane | FastAPI (Python 3.11), SQLAlchemy async, grpcio | REST `/api/v1`, server gRPC mTLS, orchestrare job-uri, workeri NATS |
| [03-agent.md](03-agent.md) | Agent Linux | Go 1.24, binar static | Daemon per host: inventar + 24 colectoare compliance, execuție job-uri, heartbeat outbound-only |
| [04-compliance.md](04-compliance.md) | Compliance Service | Go 1.25, pgx, CEL, NATS JetStream | Hot path CPU-bound: ingest snapshot-uri, drift, evaluare reguli, scoring, scheduling |
| [05-workflow-engine.md](05-workflow-engine.md) | Workflow Engine | Transversal (YAML + graf) | Automatizare multi-pași: compilare, versionare, aprobări, execuție pe agent |
| [06-infrastructura.md](06-infrastructura.md) | Infrastructură | Docker Compose, TimescaleDB, pgBouncer, NATS, Redis, mTLS | Cele 9 servicii, volume, certificate, deployment |
| [07-ansible.md](07-ansible.md) | Plugin Ansible Automation | FastAPI (gated) + Go executor | AWX-like: proiecte, roles, playbooks, templates; execuție locală securizată pe agent |
| [08-api-public-mcp.md](08-api-public-mcp.md) | API deschis & MCP (design) | FastAPI auth + PAT + MCP | Cum funcționează API-ul azi; design PAT-uri scoped + server MCP pentru clienți AI |
| [09-recomandari.md](09-recomandari.md) | Recomandări | Transversal | Remedieri prioritare (cu dovezi în cod) + implementări noi, matrice impact×efort |
| [10-compliance-autopilot.md](10-compliance-autopilot.md) | Compliance Autopilot (design) | Backend workers + settings | Baseline adopt 1-apel, assessment programat, auto-remediere gated, stări incident conectate |

## Harta generală

```
Browser ──► Frontend (:3000, Better Auth)
              │ proxy /api/v1
              ▼
          Control Plane (:8000 REST, :9090 metrics)
              │                        │ passthrough NATS
              │ gRPC :50051 mTLS       ▼
              │                  lokilinux-compliance (Go)
              ▼                        │
         Agenți Go (per host) ◄────────┘ job-uri remediere prin backend
              │ heartbeat 60s (inventar + vulnerabilități + rezultate job-uri)
              ▼
          Postgres/TimescaleDB ← pgBouncer ← toate serviciile
          NATS JetStream ─ event bus intern
          Redis ─ cache
```

## Principii transversale

1. **Agenți outbound-only** — conexiunile pornesc mereu din agent; serverul nu dial-ează niciodată.
2. **Event-driven** — NATS JetStream desincronizează procesarea grea de latența API-ului.
3. **Un singur protocol agent-server** — `proto/lokilinux.proto`, transport JSON peste gRPC, mesaje max 16 MB.
4. **Auth delegată** — Better Auth (în frontend) e sursa de adevăr; backend validează prin delegare. Roluri: ADMIN/MANAGER/OPERATOR/VIEWER/AUDITOR.
5. **Complianță hibridă** — CPU-bound în Go, CRUD în FastAPI.
6. **Totul versionat** — migrări Alembic, versiuni workflow/baseline/policy-set cu publish explicit.

## Cum citesc documentația

- Vreau să înțeleg cum ajunge un patch de la UI pe un server → citește 01 → 02 → 03, apoi fluxul „heartbeat" din 02 și „dispatch job-uri" din 03.
- Vreau să înțeleg compliance/drift → 04 (+ seria detaliată `docs/compliance/00-13`).
- Vreau să construiesc automatizări → 05.
- Vreau să instalez/operz platforma → 06 (+ README.md).

Documente conexe existente: `docs/ARCHITECTURE.md` (referință full-stack EN), `README.md` (quick start), `docs/compliance/` (spec-ul complet al modulului de compliance).
