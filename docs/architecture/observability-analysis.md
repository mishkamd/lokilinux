# LokiLinux — Observability & Critical Signal Layer: Architecture Analysis

> Audit realizat pe commit `77c4220` (v0.3.0), august 2026. Document cerut de spec-ul Observability (§2) — precede orice implementare.

## 1. Current architecture

Patru straturi verificate în cod:

| Strat | Tehnologie | Rol azi |
|---|---|---|
| Frontend | Nuxt 4 + Pinia | UI cu polling (fără WebSocket/SSE — confirmat: zero folosire reală) |
| Control Plane | FastAPI + grpcio + NATS workers | REST `/api/v1`, server gRPC mTLS :50051, 15 workeri |
| Agent Linux | Go static (CGO_ENABLED=0) | heartbeat outbound-only, job execution, compliance collectors |
| Compliance Service | Go + pgx + CEL + JetStream | ingest, drift, rules, scoring |

Infrastructură: PostgreSQL/TimescaleDB (+pgBouncer), Redis, NATS JetStream, Docker Compose (9 servicii).

## 2. Existing data flow

```
Agent → HeartbeatStream gRPC mTLS (60s) → agent_service.py → PG + NATS passthrough
                                        ← pending_jobs / policy delta / resync_domains
Compliance snapshots → NATS JetStream → Go service → tabele partajate → API reads
Remediation → plans/workers → jobs → agent executors → verification → drift RESOLVED
```

## 3. Existing agent architecture

- Bucla `Manager.Run()` cu backoff exponențial; job-uri off-loop cu guard `inFlight`; nudge channel.
- Comunicație: `communication.GRPCClient` lazy dial mTLS, **codec JSON sub numele „proto"** (`grpc_client.go:23-34`).
- Storage SQLite: rezultate job-uri neconfirmate, stări compliance; purge zilnic (`runPurge`).
- Log ring buffer 100 linii → heartbeat (`recent_logs` + contoare).
- Compliance: 24 colectoare compile-time, Normalize→Hash BLAKE3, delta-sync prin `domain_hashes`.
- Config `/etc/lokilinux/agent.yaml`: platform/identity/heartbeat/cache/job_execution/logging/file_integrity.
- **Restricție hard**: CGO_ENABLED=0 → bibliotecile care leagă libsystemd (sdjournal) NU pot fi folosite.

## 4. Existing database architecture

PostgreSQL/TimescaleDB = tot stadiul persistent. Hypertables existente: `drift_events`+`drift_details`, `inventory_snapshots`, `file_hashes/file_changes`, `rule_evaluations`, `compliance_scores`, **`agent_metrics` (migrarea 001:426-452 — MOARTĂ: nimic nu scrie în ea)**. Redis doar cache. ClickHouse: inexistent.

## 5. Existing API architecture

REST `/api/v1` FastAPI, CursorPage, `require_role` (5 roluri), OpenAPI auto la `/docs`. Serverul gRPC: `AgentServicer` cu **doar `HeartbeatStream`** implementat (`agent_service.py:64-70`); handler generic JSON `_AgentServiceHandler` (`grpc_server.py:29-44`). `ReportMetrics`/`SyncPolicy` definite în proto dar neimplementate server-side.

## 6. Existing incident architecture

**Nu există modul Incidents.** Cel mai apropiat: `drift_events` (compliance) cu dedup prin correlation key și stări OPEN→ACKNOWLEDGED→RESOLVED/SUPPRESSED; plus sistemul **Alerts** (`alerts` router + rules + AlertProcessorWorker). Decizia proiectului: corelarea semnalelor critice merge pe Alerts; Incident Engine propriu-zis = fază viitoare.

## 7. Existing compliance architecture

Documentat exhaustiv în `docs/modules/04-compliance.md`: ingest JetStream → verify BLAKE3 → content-addressable blobs → drift detect (2 baze de comparație) → CEL evaluate → scoring pe categorii. Dead inventory catalogat în `docs/modules/09-recomandari.md`.

## 8. Existing runbook architecture

**Nu există Runbooks.** Cele mai apropiate piese: playbook_templates (AWX-like) și Workflow Engine (pași + aprobări). Runbook recommendation = interfață viitoare (`IncidentAnalysisProvider`).

## 9. Existing workflow architecture

YAML v1 compilat→graf→versiuni→runs; execuție coalescată `WORKFLOW_STEPS` pe agent; poller 5s. Detalii `docs/modules/05-workflow-engine.md`.

## 10. Existing plugin architecture

Plugin-uri cu ciclu PENDING_INSTALL→ENABLED; agent-side drop în `/opt/lokilinux/plugins/`. Neafectat de observability.

## 11. Existing gaps (ce lipsește pentru Observability)

1. Zero colectare/persistare loguri sau semnale; `agent_metrics` moartă.
2. Fără ClickHouse; fără storage append-only high-volume.
3. Fără detector de semnale în agent; journald/file logs netratate.
4. Fără ingestion API dedicat; fără rate limiting per sursă.
5. Fără spool/batching/compression în agent pentru date telemetrice.
6. Fără UI observability; alerts nu primesc evenimente de tip signal.
7. Fără interfețe pentru incident/AI analysis providers.

## 12. Integration points (unde se lipește)

| Punct | Fișier | Mecanism |
|---|---|---|
| RPC nou pe canal mTLS existent | `grpc_server.py` handler + client stub reutilizând `GRPCClient.cc` | IngestObservability(stream) |
| Policy push către agent | răspuns heartbeat `update_policy` + `SyncPolicy` | câmp nou `signal_policy(+version)` |
| Corelare alerte | `workers/alert_processor.py` | subscrie `lokilinux.signal.detected`, grouping fingerprint |
| Metrics dead table activare | proto ReportMetrics + servicer + `metrics_writer.py` | hypertable `agent_metrics` |
| Rate limiting | Redis existent | counter per agent |
| Nav/UI | layouts + pages conventions | secțiune Observability |

## 13. Risks

1. Operațiunea ClickHouse (backup/upgrade/monitorizare) — a 3-a bază de date; acceptată prin decizie explicită.
2. `journalctl -f` ca follower: proces child per agent — trebuie supravegheat (restart/backoff) și cursor persistat.
3. Rotația fișierelor de log (inode/truncate) — clasică sursă de duplicare/pierdere; acoperită de teste dedicate.
4. Storm-uri (auth attacks) fără rate-limit ar putea satura agentul/rețeaua — token buckets obligatorii.
5. Cardinalitate metrici — etichete limitate la severity/type/source.

## 14. Proposed architecture

Rezumat în planul de implementare (`docs/plans/` — observability-critical-signals): agent detector (journald follower + tailers + Aho-Corasick + normalizare/fingerprint/dedup/rate-limit + spool zstd bounded) → gRPC IngestObservability pe canalul mTLS existent → Ingestion REST/gRPC backend (validare/auth/quota) → ClickHouse (4 tabele MergeTree TTL) → NATS → Alerts grouping; UI Observability; TimescaleDB rămâne exclusiv metrics (activăm tabela moartă); OTel = detecție opțională + contract REST pregătit; AI = `IncidentAnalysisProvider` interface.
