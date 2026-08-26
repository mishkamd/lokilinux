# LokiLinux Backend — Arhitectură și fluxuri

Acest document descrie backend-ul LokiLinux: limbajul, framework-urile, topologia de runtime, modul în care cererile REST, joburile, heartbeat-urile agentului și datele de compliance se deplasează prin sistem, și diagramele ASCII corespunzătoare. Este complementar documentației full-stack din [`../README.md`](../README.md) și [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) — pentru detalii despre frontend sau arhitectura generală, consultați acele fișiere.

**Clasificare arhitecturală.** Implementarea este un **modular monolith / layered hybrid** în Python `>=3.11` cu FastAPI: routere de feature pe domenii, servicii partajate de business logic, modele ORM SQLAlchemy, scheme Pydantic și workeri de fundal in-process. Nu este o arhitectură hexagonală pură — câteva routere read-only (de ex. `servers`, `categories`) interoghează SQLAlchemy direct, în timp ce serviciile dețin majoritatea căilor de scriere și mașinilor de stare.

**Două procese de runtime din același cod.** Un singur codebase este deployat ca două procese separate din aceeași imagine Docker:

- `uvicorn lokilinux.main:app --host 0.0.0.0 --port 8000 --workers 2` — serverul REST + 19 workeri NATS/asyncio pe portul `:8000` (+ metrici Prometheus pe `:9090`).
- `python -m lokilinux.grpc_server` — serverul gRPC pentru comunicarea cu agenții Go, pe portul `:50051` cu mTLS reciproc (metrici Prometheus pe `:9091`).

Serviciul Go `lokilinux-compliance` (`services/compliance/`) este un participant extern, conectat prin NATS și PostgreSQL — **nu** un pachet Python în backend.

---

## Tehnologii și componente

| Componentă | Versiune / pachet | Rol |
|---|---|---|
| Python | `>=3.11` (3.11-slim în Docker) | Runtime |
| FastAPI | 0.138.1 | Framework HTTP async |
| Uvicorn | 0.49.0 | Server ASGI |
| Pydantic / Pydantic Settings | 2.13.4 / 2.14.2 | Validare scheme + configurare din mediu |
| ORJSON | 3.11.9 | Serializer JSON rapid |
| SQLAlchemy async | 2.0.51 | ORM cu session async |
| psycopg | 3.3.4 (async + binary) | Driver PostgreSQL |
| Alembic | 1.18.5 | Migrații de schemă (001→034) |
| PostgreSQL / TimescaleDB | 2.28.1-pg17 | Stocare principală + serie temporală |
| pgBouncer | 1.25.2-p0 | Connection pooling |
| Redis | redis-py 8.0.1 (hiredis) | Cache-aside, rate-limit, enrollment tokens, stare corelație |
| NATS | 2.15.0 (nats-py) | Bus de evenimente; serverul Compose pornește cu JetStream (`--js`), dar codul Python folosește API-urile standard subject publish/subscribe |
| ClickHouse | clickhouse-connect 1.7.2 | Event store: raw events, signal occurrences, incident evidence (`ch.py`) |
| OpenTelemetry | opentelemetry-proto 1.44.0 | Definiții protobuf pentru ingest OTLP/HTTP (`/api/v1/otlp`) — fără SDK/exporter |
| grpcio | 1.81.1 | Server gRPC pentru agenți (JSON codec) |
| PyJWT + cryptography | 2.13.0 / 46.0.3 | Verificare semnătură Ed25519 pachete job (KMS), X.509 enroll certs |
| prometheus-client | 0.21.1 | Metrici Prometheus pe `metrics.py` (HTTP server :9090 api / :9091 grpc) |
| httpx | 0.28.1 | Client HTTP pentru Better Auth session validation |
| structlog | 26.1.0 | Logging structurat |
| croniter | 6.2.4 | Scheduling policy/workflow pe expresii cron |
| openpyxl / reportlab | 3.1.5 / 5.0.0 | Export compliance XLSX/PDF |
| PyYAML | 6.0.3 | Loader reguli compliance curated |

**Participanți externi:**

- **Frontend:** Nuxt 4 + Better Auth pe `:3000`
- **Agenți Go:** demoni Linux care se conectează la gRPC cu mTLS
- **lokilinux-compliance (Go):** microserviciu separat în `services/compliance/`, integrat prin NATS + PostgreSQL

### Topologie deployment — Arhitectura ASCII

```text
                         +-----------------------------+
                         | Nuxt 4 / Better Auth :3000  |
                         +--------------+--------------+
                                        | REST /api/v1
                                        v
                         +--------------+--------------+
                         | lokilinux-api :8000         |
                         | FastAPI + 19 workers        |
                         | Prometheus metrics :9090    |
                         +------+-----------+----------+
                                |           |
                                |           +--> Redis :6379
                                +--------------> NATS :4222
                                |           |
                                |           +--> ClickHouse :8123 (events)
                                v
                         pgBouncer
                                |
                                v
                      PostgreSQL/TimescaleDB :5432

Go Linux agents -- mTLS HeartbeatStream --> +------------------------+
                                            | lokilinux-grpc :50051  |
                                            | separate Python process|
                                            | Prometheus metrics:9091|
                                            +----+------+------------+
                                                 |      |
                                                 +--> Redis/NATS
                                                 +--> pgBouncer -> PostgreSQL

NATS :4222 <--> lokilinux-compliance (Go) -----> PostgreSQL/TimescaleDB
```

Ambele procese Python (API și gRPC) își creează propriile conexiuni la DB/cache/NATS — nu împart clienți. Doar procesul API are conexiune ClickHouse (pipeline-ul de observaibilitate rulează în workerii API). Agenții se conectează exclusiv la procesul gRPC separat. Compliance este integrat prin NATS și baza de date partajată, nu prin apel Python direct.

### Porturi și servicii Compose

| Serviciu | Port(uri) | Descriere |
|---|---|---|
| `lokilinux-api` | `8000:8000`, `9090:9090` | REST FastAPI; `9090` servește metrici Prometheus (`metrics.py`, prometheus_client HTTP server) |
| `lokilinux-grpc` | `50051:50051` | Server gRPC Python, JSON codec, mTLS; metrici interne pe `9091` |
| `lokilinux-migrate` | — | One-shot: `alembic upgrade head` |
| `lokilinux-compliance` | niciun port public | Go microservice (drift/baseline/scoring); healthcheck self-bin `-healthcheck` |
| `lokilinux-frontend` | `3000:3000` | Nuxt 4 |
| `postgres` | intern `5432` | TimescaleDB |
| `pgbouncer` | intern `5432` | Connection pool |
| `redis` | intern `6379` | Cache |
| `nats` | intern `4222` (client), `8222` (monitor) | Bus evenimente cu JetStream, auth obligatoriu |
| `clickhouse` | intern `8123` | Event store (raw events, signal occurrences, incident evidence) |

---

## Structura codului

```text
backend/
├── lokilinux/
│   ├── main.py               # FastAPI assembly, lifespan, middleware, health, /downloads, /api/v1
│   ├── config.py             # Settings (env) — DATABASE_URL, BETTER_AUTH_URL, metrics, etc.
│   ├── settings_schema.py    # Platform settings (DB-backed, group.key)
│   ├── db.py                 # Async engine + session factory + get_db dependency
│   ├── cache.py              # RedisCache cache-aside + TTL constants
│   ├── dependencies.py       # get_db, get_cache, get_nats (request-scoped)
│   ├── nats_topics.py        # Single source of truth pentru subjecte NATS
│   ├── grpc_server.py        # Bootstrap gRPC: JSON codec, mTLS, port 50051 + metrics :9091
│   ├── metrics.py            # Prometheus metrici securitate/pipeline + start_metrics_server()
│   ├── ch.py                 # ClickHouse client + batch writer (events/occurrences/evidence)
│   ├── install_agent.sh.tmpl # Template installer agent (rendered de /agent/install.sh)
│   ├── events/               # Observability: NormalizedEvent schemas + ClickHouse repository
│   ├── signals/              # Detectoare de semnale per tip eveniment + SignalService (dedup/upsert)
│   ├── incidents/            # Ciclu de viață incidente: timeline, root cause, evidence (ClickHouse)
│   ├── correlation/          # Weighted-window evaluator + stare Redis + supresie
│   ├── runbooks/             # Bridge incident → workflow (auto-trigger safe-by-default)
│   ├── otlp/                 # Ingest OTLP/HTTP → traducere în evenimente normalizate
│   ├── topology/             # Model noduri/muchii cu resolver recursiv
│   ├── api/v1/
│   │   ├── __init__.py       # Router aggregator + prefixe
│   │   └── routers/          # Routere feature (dashboard, jobs, servers, events, signals,
│   │   │                     #   incidents, correlation, topology, runbooks, observability,
│   │   │                     #   otlp, ...) 
│   │   └── compliance/       # Sub-routere compliance (baselines, drift, inventory, etc.)
│   ├── api/grpc/
│   │   └── agent_service.py  # AgentServicer — HeartbeatStream bidirecțional
│   ├── auth/
│   │   ├── jwks_validator.py # get_current_user — delegare Better Auth session
│   │   └── dependencies.py   # require_role, safe_user_uuid
│   ├── middleware/
│   │   └── rate_limit.py     # Rate limit Redis-backed, fail-open
│   ├── models/               # Modele ORM SQLAlchemy (27 module — inclus signals/incidents/topology/runbooks/workflows)
│   ├── schemas/              # Scheme Pydantic (request/response)
│   ├── services/             # Logică de business (31 fișiere)
│   └── workers/              # Consumatori NATS + bucle asyncio (19 workeri)
├── alembic/                  # Migrații 001 → 034
├── tests/
│   ├── conftest.py
│   ├── unit/                 # 44 suite-uri unitare (test_*)
│   └── integration/          # 17 suite-uri de integrare (test_*)
├── pyproject.toml
├── Dockerfile                # Production: uvicorn --workers 2
├── Dockerfile.dev            # Development: uvicorn --reload
└── alembic.ini
```

### Responsabilități pe modul

| Modul | Rol |
|---|---|
| `main.py` | Assembly FastAPI: `lifespan()` (engine, cache, NATS, ClickHouse, 19 workeri), middleware (CORS, GZip, rate-limit, request-id), health probes (`/health`, `/ready`), Prometheus metrics server (`metrics_enabled`, port `metrics_port` 9090), mount `/downloads` (pachete agent), `/api/v1`, validation handler → 422 |
| `config.py` | `Settings(BaseSettings)` — configurare din variabile de mediu: `database_url`, `redis_url`, `nats_url`, `grpc_port`, `better_auth_url`, `better_auth_secret`, `agent_cert_dir`, `frontend_url`, `platform_url`, `agent_version`, `agent_package_dir` |
| `settings_schema.py` | Platform settings stocate în tabelul `settings` (`group.key`), separate de `config.py` care citește din mediu; `get_setting_value()` cu cast per-tip; chei secrete mascate |
| `db.py` / `dependencies.py` | `build_engine()` (pool_size=20, max_overflow=10, pool_recycle=3600, pool_pre_ping), `build_session_factory()` (autoflush=False), `get_db()` cu commit pe succes / rollback pe excepție, `get_cache()` și `get_nats()` din `app.state` |
| `api/v1/` | Routere montate la `/api/v1`: `/dashboard`, `/categories` (fără prefix), `/compliance/*`, `/servers`, `/jobs`, `/vulnerabilities`, `/policies`, `/plugins`, `/playbooks`, `/playbook-templates`, `/ansible-roles`, `/ansible-projects`, `/alerts`, `/admin`, `/agent` (install/packages/download), `/agents/register`, plus suită de observaibilitate: `/events`, `/signals`, `/incidents`, `/correlation`, `/topology`, `/runbooks`, `/observability` (readout pe metricile pipeline-ului proprii) și `/otlp` (ingest OTLP/HTTP). Auth Better Auth nu se aplică pe `/health`, `/ready`, `/agent/install.sh`, `/agent/download-latest`, `/agent/download` (cu token enrollment), și `/agents/register` (cu token enrollment) |
| `api/v1/routers/agent_install.py` | Flux enrollment: ADMIN/OPERATOR creează token Redis `enrollment:{token}` cu TTL 86400s; `GET /agent/install.sh` renderizează `install_agent.sh.tmpl` (public); `GET /agent/download` și `POST /agents/register` validează token-ul din Redis; la register se generează certificatul mTLS semnat de CA local |
| `services/` | `AgentService`, `JobService`, `AlertService`, `PolicyService`, `BaselineService`, `RemediationService`, `ReportService`, `CVEService`, `PluginService`, `PlaybookService`, `AnsibleRoleService`, `AnsibleProjectService`, `PlaybookTemplateService`, `AuditService`, `compliance_ingest_service`, `complianceascode_importer` — aceleași funcții sunt reutilizate de HTTP, gRPC și workeri |
| `models/` / `schemas/` | SQLAlchemy `Base` cu JSONB/enum pentru persistență vs. Pydantic `model_validate` pentru conversia request→response; `models/__init__.py` importă toate cele 28 de modele pentru `Base.metadata` (necesar Alembic) |
| `workers/` | Consumatori de evenimente NATS și bucle asyncio — detaliate în secțiunea [Fluxul agentului și joburilor](#fluxul-agentului-și-joburilor) |

**Regula de stratificare.** Routerele sunt subțiri pentru scrierile servite de servicii. Citirile directe SQLAlchemy rămân în câteva routere (de ex. `servers`, `categories`, `dashboard`) — documentul numește aceasta *layered hybrid*, nu *service-only boundary*.

---

## Cum pornește și procesează cererile

### `lifespan()` — ordinea de pornire

Definită în `lokilinux/main.py`, executată o singură dată la pornirea procesului:

1. **Baza de date.** `build_engine(settings.database_url)` → `build_session_factory(engine)` → stocate în `app.state.db_engine` și `app.state.session_factory`.
2. **Redis.** `RedisCache(url=settings.redis_url).connect()` → `app.state.cache`.
3. **NATS.** `nats.connect(settings.nats_url)` → `app.state.nats`.
4. **Metrici.** Dacă `metrics_enabled` (default `true`) — `start_metrics_server(settings.metrics_port)` pornește serverul HTTP prometheus_client pe `:9090`.
5. **19 workeri** porniți după ce NATS este disponibil:
   - Clasic: `JobExecutorWorker`, `CVEProcessorWorker`, `AlertProcessorWorker`, `PolicyWorker`, `PolicySchedulerWorker`, `PluginWorker`, `HeartbeatMonitorWorker`, `JobTimeoutWorker`, `RetentionCleanupWorker`, `RemediationSchedulerWorker`, `RemediationVerificationWorker`, `NotificationWorker`, `CVEEnrichmentWorker`.
   - Workflow engine: `WorkflowRunnerWorker` (avansează run-urile RUNNING, poller 5s), `WorkflowSchedulerWorker` (declanșatoare cron).
   - Observability pipeline: `EventProcessorWorker` (`lokilinux.events.raw` → ClickHouse), `SignalProcessorWorker` (`lokilinux.events.normalized` → detectoare → semnale), `CorrelationWorker` (`lokilinux.signals.detected` → evaluator fereastră ponderată → incidente), `IncidentWorker` (watcher `SIGNAL_RESOLVED` + sweeper auto-resolve).
6. **Servește cereri.**
7. **Shutdown** — ordine inversă: `stop()` explicit pe workerii pe buclă `asyncio` (fără subscriere NATS): `HeartbeatMonitorWorker`, `RemediationVerificationWorker`, `RemediationSchedulerWorker`, `JobTimeoutWorker`, `PolicySchedulerWorker`, `RetentionCleanupWorker`, `CVEEnrichmentWorker`, `WorkflowRunnerWorker`, `WorkflowSchedulerWorker`, `SignalProcessorWorker*`, `CorrelationWorker*`, `IncidentWorker*`; apoi `nc.drain()` (NATS), `cache.disconnect()` (Redis), `engine.dispose()` (DB). Workerii subscriberi NATS (`JobExecutorWorker`, `CVEProcessorWorker`, `AlertProcessorWorker`, `PolicyWorker`, `PluginWorker`, `NotificationWorker`, `EventProcessorWorker`) sunt eliberați de `nc.drain()`. (*mixed: loop + subscripție — vezi `workers/*.py` pentru shape-ul exact.)

### Fluxul unei cereri HTTP

```text
HTTP request
    |
    v
CORS/GZip/rate-limit/request-id logging
    |
    v
Bearer session + role/plugin dependencies
    |
    v
v1 router + Pydantic schema
    |
    +--> service/application logic ----> SQLAlchemy async session ----> PostgreSQL
    |             |                              |
    |             +------------------------------+--> NATS event
    |                                            |
    +-------------------- Redis cache-aside <----+
    |
    v
ORJSON response / 4xx sau 5xx boundary
```

**Legătura cu codul:**

- **Middleware:** CORS (originea din `frontend_url`), GZip (minim 1024 bytes, nivelul 6), rate-limit Redis (fail-open dacă DB/cache indisponibil), request-id tracing (`X-Request-ID`).
- **`get_db`** yield-uieste o sesiune: commit automat la ieșirea normală, rollback la excepție.
- **Cache-aside** cu prefixe de chei și TTL-uri standardizate (`cache.py`):
  - `agent:{id}:status` → 30s
  - `job:{id}:status` → 60s
  - `cve:*` → 3600s
  - `server:list:*` → 86400s
  - Invalidare pe pattern (`agent:{id}:*`, `vulnerability:{id}:*`, `cve:*`).
- **Erori Redis** sunt logate și fail-open în cache/rate-limit — nu blochează cererea.
- **Validare** → HTTP 422 cu `{"detail": "Validation error", "errors": [...]}` (max 5).
- **`/health`** → `{"status": "ok"}` (liveness, fără verificări externe).
- **`/ready`** → execută `SELECT 1` pe DB + `cache.ping()` pe Redis; returnează 503 cu `{"status": "not_ready", "errors": [...]}` dacă oricare eșuează.

### Autentificare

Implementarea din `auth/jwks_validator.py` și `auth/dependencies.py`:

- **Bearer token lipsă/invalid** → 401.
- **Cache pozitiv** per-token în Redis, TTL 60s — evită request la Better Auth per cerere.
- **Better Auth indisponibil tranzitoriu:** 2 încercări cu delay de 1s între ele; dacă ambele eșuează (network error sau 5xx), negative cache 5s (`ba:down:{token}`) și se returnează 503.
- **401/403 de la Better Auth** → 401 (`"Invalid or expired token"`).
- **Alt cod non-200** → 502.
- **Sesiune validă** → datele user-ului cu role normalizat la uppercase; cache pozitiv 60s.
- **`require_role(*roles)`** → 403 dacă rolul nu este în listă; **ADMIN trece mereu**, indiferent de rolurile cerute.
- **`safe_user_uuid()`** → încearcă `UUID(user["id"])`; returnează `None` dacă Better Auth returnează un nanoid care nu parsează ca UUID (caz frecvent) — coloanele de audit `created_by`/`acknowledged_by` (UUID) primesc `None` în loc să eșueze.

> **Notă:** Comentariile din `config.py` menționează „JWKS” și „RS256”, dar implementarea curentă **nu** face validare JWKS locală. Autentificarea deleghează la `GET {BETTER_AUTH_URL}/api/auth/get-session` cu header-ul `Authorization: Bearer <token>` al clientului. `BETTER_AUTH_SECRET` este cerut de `Settings` și de Compose, dar backend-ul nu-l folosește pentru semnare/verificare locală de token-uri.

---

## Fluxul agentului și joburilor

### gRPC HeartbeatStream

```text
Go agent (fiecare heartbeat)
        |
        | mTLS bidirectional HeartbeatStream
        v
lokilinux.grpc_server :50051
        |
        v
AgentServicer -> AgentService.update_heartbeat()
        |             |-- agent/system/health/package/CVE sync -> PostgreSQL
        |             |-- cache invalidation
        |             +-- reported job_results -> JobService aggregation
        |
        +--> get_pending_jobs(): approval gate, max 10, mark RUNNING
        +--> compliance hash diff + snapshot publish -> NATS
        |
        v
response: pending_jobs + per-agent parameters + resync_domains
```

**Detalii de implementare din `grpc_server.py` și `agent_service.py`:**

- `grpc_server.py` înregistrează `lokilinux.AgentService/HeartbeatStream` ca handler generic stream-stream (`_AgentServiceHandler`) cu **JSON codec** (serialize/deserialize `json.dumps`/`json.loads` cu `SimpleNamespace` ca object hook). Repository-level `../proto/lokilinux.proto` rămâne referința de schemă, dar wiring-ul runtime curent nu folosește protobuf binary — transmite JSON.
- **mTLS reciproc:** `grpc.ssl_server_credentials(..., require_client_auth=True)` cu certificate CA/server din `CA_CERT_PATH`, `SERVER_CERT_PATH`, `SERVER_KEY_PATH` (montate de Compose din volumul `certs_dir`).
- **Limite mesaj:** `grpc.max_recv_message_length` și `grpc.max_send_message_length` = 16 MiB.
- **Proces separat** cu propriul engine SQLAlchemy, RedisCache și conexiune NATS — nu împarte nothing cu procesul REST.
- **AgentServicer.HeartbeatStream:** primește `agent_id`, `ip_address` (fallback la peer address gRPC), `system_status`, `packages`, `health`, `job_results`, `vulnerabilities`, `agent_version`, `domain_hashes`, `domain_full`. Pentru fiecare mesaj:
  1. `AgentService.update_heartbeat()` persistă agentul, sistemul, pachetele, sănătatea, vulnerabilitățile; invalidează cache-ul agentului.
  2. `job_results` raportate de agent → `JobService.complete_job()` per rezultat.
  3. `get_pending_jobs(agent.id)` → filtrare pe `approved_at`, limită 10, marchează `RUNNING` cu `started_at`.
  4. Compliance: `diff_domain_hashes()` compară hash-urile agentului cu `InventorySnapshot` stocate; domeniile diferite/lipsă sunt returnate în `resync_domains`; `publish_domain_snapshots()` publică `lokilinux.compliance.snapshot.{domain}` per domeniu din `domain_full` (sari peste domenii fără hash corespunzător).
  5. Response: `pending_jobs` (cu `job_id`, `job_type`, `parameters` filtrate per-agent pentru `COMPLIANCE_REMEDIATE`, `timeout_seconds` opțional) și `resync_domains`.

### Ciclul de viață al unui job

```text
POST /api/v1/jobs sau policy trigger
        |
        v
JobService.create_job()
  SHA-256 dedup key + one JobResult(PENDING)/agent
        |
        +--> duplicate active job -> 409
        +--> JOB_CREATED -> NATS
        v
next agent heartbeat -> approval check -> PENDING to RUNNING
        |
        v
result via heartbeat (calea principală curentă)
        |
        v
complete_job() -> recompute_job_status() -> PostgreSQL
        +--> Redis job-status invalidation
        +--> timeout worker marchează joburile stale non-terminale TIMEOUT
```

**Detalii din `job_service.py`:**

- **Deduplicare:** `compute_dedup_key()` = SHA-256 pe `job_type:target_servers:parameters` (sortate); verifică joburi active (`QUEUED`, `SCHEDULED`, `PENDING`, `RUNNING`) → `ValueError("Duplicate job already active")` → HTTP 409. `IntegrityError` pe `uq_jobs_dedup_key` (migrația 020) prinde race conditions între SELECT și COMMIT.
- **Fan-out per agent:** un `JobResult(status=PENDING)` pentru fiecare `agent_id` din `target_servers.agent_ids`.
- **Aprobare:** `requires_approval=True` → jobul nu ajunge la agent până la `approve_job()` care setează `approved_at`; `get_pending_jobs()` verifică `approved_at IS NOT NULL`.
- **Publicare:** `JOB_CREATED` pe NATS la creare (chiar și pentru joburi cu aprobare — vizibilitate dashboard).
- **Completare:** `complete_job(job_id, agent_id, exit_code, stdout, stderr, duration_ms)` → status `COMPLETED` (exit_code 0) sau `FAILED`; **cap stdout 50 KB**, **cap stderr 10 KB**; `recompute_job_status()` agregă toate `JobResult`-urile:
  - Toate terminale → status final: `FAILED`/`TIMEOUT`/`CANCELLED` (prima din `_FAILURE_PRIORITY` care match-uieste), altfel `COMPLETED`.
  - Parțial terminale → `PARTIALLY_COMPLETED` + `started_at`.
  - Niciunul terminal → `RUNNING` + `started_at`.
  - `CANCELLED` manual este final — un raport târziu de la agent nu-l redeschide.
- **Cache:** invalidare `job:{id}:status` după fiecare completare sau aprobare.
- **`JobExecutorWorker`** subscribe la `lokilinux.job.result` — prezent în cod ca subscriber NATS real, dar **nu există un publisher activ** pentru acest subject în sursa backend inspectată. Documentat ca path dormant/disponibil, diferit de calea principală prin heartbeat.

### Tabel workeri

Din `main.py:lifespan` și `nats_topics.py`:

**Subscriberi NATS:**

| Worker | Subiect(e) | Rol |
|---|---|---|
| `JobExecutorWorker` | `lokilinux.job.result` | Subscriber dormant (niciun publisher curent în backend) |
| `CVEProcessorWorker` | `lokilinux.cve.database.updated` | Procesare update-uri bază CVE |
| `AlertProcessorWorker` | `lokilinux.agent.unhealthy` | Procesare alerte de sănătate agent |
| `NotificationWorker` | `lokilinux.alert.created` | Notificări (best-effort, SMTP prin `asyncio.to_thread`) |
| `PolicyWorker` | `lokilinux.policy.changed`, `lokilinux.policy.apply` | Aplicare policy la schimbare/cerere explicită |
| `PluginWorker` | `lokilinux.plugin.install`, `lokilinux.plugin.uninstall` | Instalare/dezinstalare plugin-uri |
| `EventProcessorWorker` | `lokilinux.events.raw` | Validează, dedup (Redis), fingerprint, batch-insert în ClickHouse → publică `lokilinux.events.normalized` |

**Bucle asyncio (+ subscripție unde notat):**

| Worker | Interval / Subiect | Rol |
|---|---|---|
| `WorkflowRunnerWorker` | 5s | Avansează fiecare workflow run RUNNING (compilație pas-cu-pas, coalescing pași agent) |
| `WorkflowSchedulerWorker` | 30s | Declanșează workflows cu trigger cron SCHEDULE |
| `SignalProcessorWorker` | loop + sub `lokilinux.events.normalized` | Rulează detectori per tip eveniment → dedup/upsert semnale → publică `lokilinux.signals.detected` |
| `CorrelationWorker` | sub `lokilinux.signals.detected` + loop | Evaluator fereastră ponderată per `correlation_rules`, stare Redis, supresie → creează/actualizează incidente |
| `IncidentWorker` | watcher `SIGNAL_RESOLVED` + sweeper | Watcher auto-resolve pe rezolvarea semnalelor; sweeper pentru life-cycle stale; scrie evidence în ClickHouse |
| `PolicySchedulerWorker` | 30s | Atomic claim + `run_policy()` pentru policy-uri cu trigger cron |
| `HeartbeatMonitorWorker` | 60s | Sweep joburi ACTIVE stale → publică `lokilinux.agent.unhealthy` |
| `JobTimeoutWorker` | 60s | Marchează joburi non-terminale depășite ca `TIMEOUT` |
| `RemediationSchedulerWorker` | 30s | Dispatch joburi de remediere aprobate în ferestre de mentenanță |
| `RetentionCleanupWorker` | 3600s | Purjare audit log conform politicii de retenție |
| `CVEEnrichmentWorker` | loop tick-based | Completează CVSS/titlu/descriere/CWE/date pentru CVE-uri |
| `RemediationVerificationWorker` | tick | Închide bucla pe planurile VERIFYING (verificare post-remediere) |

**Gestionarea erorilor la subscriberi:** callback-urile loghează erorile; notificările sunt best-effort; workerii de invalidare cache nu execută acțiuni pe agent — agentul primește lucru (plugin/job) la următorul heartbeat. `PolicyService.run_policy()` este partajat de trigger-ele manuale și programate și skip-uiește silențios cazurile no-action/no-target/active-duplicate.

---

## Compliance, date și deployment

### Flux compliance

```text
Agent domain_hashes/domain_full
            |
            v
Python AgentServicer + compliance_ingest_service
  diff known InventorySnapshot hashes
  publish lokilinux.compliance.snapshot.<domain>
            |
            v
Go lokilinux-compliance
  ingest / baseline / rules / drift / score
            |
            +--> PostgreSQL/TimescaleDB
            +--> result events on NATS
            v
FastAPI /api/v1/compliance/* + reports
```

**Edge cases dovedite din sursă:**

- **Hash-uri goale** → `diff_domain_hashes()` returnează `[]`, niciun publish.
- **Domeniu schimbat/lipsă** → returnat în `resync_domains`; agentul trimite `domain_full` la următorul heartbeat.
- **`domain_full` fără hash corespunzător** → `publish_domain_snapshots()` loghează warning și **sari peste publish** (nu publică date fără hash de verificat).
- **Raport compliance:** creare → HTTP 202, persistă `ComplianceReport(status=PENDING)`, rulează `generate_report` ca FastAPI background task (XLSX/PDF); download → 409 până la `status=COMPLETED`.
- **Rezultate compliance** de la Go: scrise **direct în PostgreSQL** (`compliance_scores`, tabele drift) — citite de routerele `/compliance/*`; `lokilinux.compliance.baseline.published` este consumat intern pentru rezolvarea baseline-urilor efective per agent. Nu există subiecte „drift.detected” / „score.updated” în sursa curentă.

### Suita de observaibilitate (events → signals → incidents)

Adăugată în v0.4.0 — patru pachete noi + depozit ClickHouse:

```text
producători: agenți (metric.sample pe heartbeat), REST intern,
             OTLP/HTTP POST /api/v1/otlp (opentelemetry-proto)
   │
   ▼
lokilinux.events.raw ──► workers/event_processor.py
   │                      • validare NormalizedEvent (events/schemas.py)
   │                      • dedup Redis ev:dedup:{event_id}
   │                      • fingerprinting; batch insert prin ch.py
   ▼                     publică lokilinux.events.normalized
ClickHouse: tabelul events (+ buffer depth/dropped metrics)
   │
   ▼
workers/signal_processor.py ──► signals/detectors.py (registru per tip eveniment)
   │                            signals/service.py — dedup/upsert semnale
   ▼                            publică lokilinux.signals.detected
workers/correlation_worker.py ──► correlation/evaluator.py
   │                              • ferestre ponderate per CorrelationRule
   │                              • stare parțială în Redis; supresie per regulă
   ▼                              • match → IncidentService open/append evidence
workers/incident_worker.py ──► incidents/service.py
   • watcher SIGNAL_RESOLVED → auto-resolve incidente deschise
   • sweeper pentru tranziții ratate; rânduri incident_evidence în ClickHouse
   ▼  publică lokilinux.incidents.created / updated / resolved
runbooks/service.py ──► pod incident → workflow (auto-trigger doar cu autorun_enabled)
```

- **`ch.py`** — client clickhouse-connect + batch writer: `events`, signal occurrences, `incident_evidence`; contoare `clickhouse_insert_errors_total`, `events_dropped_total`, `event_buffer_depth` în `metrics.py`.
- **Retenție:** env-tunable — `EVENT_RETENTION_DAYS` (30), `SIGNAL_OCCURRENCE_RETENTION_DAYS` (90), `INCIDENT_EVIDENCE_RETENTION_DAYS` (180).
- **OTLP (`otlp/translate.py`)** — convertește payload-uri protobuf OTLP în `NormalizedEvent`; integritate asigurată de același dedup ca evenimentele interne.
- **API read model:** `/events`, `/signals`, `/incidents`, `/correlation` (CRUD reguli), `/topology` (noduri/muchii + resolver recursiv), `/runbooks`, plus `/observability` care expune contoarele pipeline-ului direct din obiectele prometheus_client.

### Persistență

Modelele ORM din `lokilinux/models/` acoperă:

- **Agenți și inventar:** `Agent`, `AgentHealth`, `AgentMetrics`, `AgentStatus`, `InventoryBlob`, `InventoryDelta`, `InventorySnapshot`
- **Joburi:** `Job`, `JobResult`, `JobStatus` (enum)
- **CVE / pachete / vulnerabilități:** `CVE`, `Package`, `PackageVulnerability`, `AgentVulnerability`
- **Policy / audit:** `Policy`, `PolicyAudit`, `AuditLog`, `Setting`, `UserProfile`, `UserRole`, `RoleAssignment`
- **Compliance:** `Baseline`, `BaselineApproval`, `BaselineEffective`, `BaselineVersion`, `ComplianceRule`, `PolicyAssignment`, `PolicySet`, `PolicySetRule`, `RemediationTemplate`, `ComplianceScore`, `RuleEvaluation`, `DriftDetail`, `DriftEvent`, `FileChange`, `FileHash`, `ComplianceReport`
- **Remediere:** `MaintenanceWindow`, `RemediationAction`, `RemediationJob`, `RemediationPlan`
- **Ansible / playbooks:** `AnsibleRole`, `AnsibleProject`, `Playbook`, `PlaybookTemplate`
- **Workflow engine:** `Workflow`, `WorkflowVersion`, `WorkflowRun`, `WorkflowStep` (migrația 028)
- **Observability:** `Signal`, `CorrelationRule` (migrația 031), `Incident` + relații/timeline + `alerts.incident_id` (migrația 032), `TopologyNode`/`TopologyEdge` (migrația 033), `Runbook` (migrația 034)
- **Plugin-uri:** `Plugin`, `PluginInstallation`, `PluginStatus`
- **Altele:** `Category`, `Project`, `Alert`, `AlertRule`

Datele de observaibilitate volumice **nu** stau în Postgres: raw events, signal occurrences și incident evidence sunt rânduri ClickHouse scrise de `ch.py`; Postgres păstrează doar entitățile reglabile (semnale dedup, reguli, incidente, topologie, runbooks).

`alembic/env.py` importă `lokilinux.models` (toate modelele înregistrate pe `Base.metadata`), citește `Settings.database_url`, și rulează `alembic upgrade head`. **Nu există un strat repository/DAO separat** — serviciile accesează sesiunea SQLAlchemy direct.

Migrații: 34 fișiere (`001_initial_schema` → `034_runbooks`).

### Deployment

**Producție / Development cu Compose:**

```bash
# Din repository root (/opt/lokilinux/)
cp .env.example .env
make init       # Prima rulare: certificate + volume + build/start + migrații/admin init
make dev        # Override development cu hot-reload
```

**Direct din `backend/`:**

```bash
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn lokilinux.main:app --reload --host 0.0.0.0 --port 8000
python -m lokilinux.grpc_server
pytest -q
```

**Configurare container:**

- `lokilinux-migrate`: `restart: "no"`, one-shot `alembic upgrade head`, dependent de pgBouncer healthy.
- `lokilinux-api`: `Dockerfile` cu CMD `uvicorn lokilinux.main:app --host 0.0.0.0 --port 8000 --workers 2`; dependent de pgBouncer, NATS, Redis healthy + migrate completed.
- `lokilinux-grpc`: aceeași imagine, CMD `python -m lokilinux.grpc_server`; dependent de pgBouncer, NATS, Redis.
- `Dockerfile.dev`: CMD `uvicorn ... --reload` (hot-reload pentru development).
- `python -m lokilinux.main` (direct) folosește `API_WORKERS` (default 4).

**Setări necesare** (din `config.py` + Compose):

| Variabilă | Descriere |
|---|---|
| `DATABASE_URL` | Obligatorie. URI PostgreSQL+psycopg către pgBouncer |
| `BETTER_AUTH_URL` | Obligatorie. URL-ul instanței Better Auth (Nuxt) |
| `BETTER_AUTH_SECRET` | Obligatorie. Secret partajat (necesar în `Settings`, deși backend-ul nu-l folosește pentru semnare locală) |
| `REDIS_URL` | Default: `redis://localhost:6379` |
| `NATS_URL` | Default: `nats://localhost:4222` |
| `CLICKHOUSE_URL` | Default din Compose: `http://clickhouse:8123`; cu `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` / `CLICKHOUSE_DATABASE` |
| `EVENT_RETENTION_DAYS` / `SIGNAL_OCCURRENCE_RETENTION_DAYS` / `INCIDENT_EVIDENCE_RETENTION_DAYS` | Retenție ClickHouse per dataset (30/90/180) |
| `METRICS_ENABLED` / `METRICS_PORT` | Server Prometheus (default `true` / `9090`; grpc: `9091`) |
| `GRPC_PORT` | Default: `50051` |
| `CA_CERT_PATH`, `SERVER_CERT_PATH`, `SERVER_KEY_PATH` | Certificate mTLS; citite direct de `grpc_server.py`, montate de Compose din `certs_dir` |
| `AGENT_CERT_DIR` | Default: `/etc/lokilinux/certs` |
| `FRONTEND_URL` | Default: `http://localhost:3000` (CORS origin) |
| `PLATFORM_URL` | Default: `http://localhost:8000` |
| `AGENT_VERSION` | Default în `config.py`: `0.1.0`; Compose: `${AGENT_VERSION:-0.35.3}` — **configurație-driven**, sursa de adevăr depinde de contextul de deployment |
| `AGENT_PACKAGE_DIR` | Default: `/opt/lokilinux/packages` |

---

## Note despre sursa de adevăr

Acest document reflectă starea **curentă a sursei**, nu comentarii sau documente învecinate care pot fi învechite. Discrepanțe concrete față de alte surse:

1. **Autentificare:** codul curent apelează `GET {BETTER_AUTH_URL}/api/auth/get-session` pentru validare sesiune (`auth/jwks_validator.py`), în ciuda numelui fișierului și a referințelor „JWKS” / „RS256”. `PyJWT`+`cryptography` din dependențe sunt folosite pentru verificarea pachetelor job semnate Ed25519 (KMS), nu pentru sesiuni.

2. **gRPC codec:** serverul gRPC curent folosește **JSON serializers** (`json.dumps`/`json.loads` cu `SimpleNamespace`). Fișierul `../proto/lokilinux.proto` există la nivel de repository ca referință de schemă, dar wire-ul runtime nu folosește protobuf binary.

3. **Workeri:** `main.py` pornește curent **19 workeri** (13 clasice + WorkflowRunner/WorkflowScheduler + EventProcessor/SignalProcessor/Correlation/Incident). Nu repetați rezumatele învechite de „10/11 workeri”.

4. **Metrici Prometheus:** există acum efectiv — `metrics.py` pornește un server HTTP prometheus_client: `:9090` pe `lokilinux-api`, `:9091` pe `lokilinux-grpc` (`METRICS_ENABLED` / `METRICS_PORT`). Nu confundați `/servers/{agent_id}/metrics` (endpoint de date pentru metricile agentului) cu endpoint-ul Prometheus. Routerul `/observability` citește direct obiectele de metrici ale pipeline-ului propriu, nu registry-ul global.

5. **Versiune agent:** `config.py` definește un default local, în timp ce Compose setează `AGENT_VERSION: ${AGENT_VERSION:-0.37.0}` — configurație-driven. La runtime, valoarea servită vine din DB (`settings.agent.version`, updatată de release flow); build-side SSOT este `agent/VERSION`, sincronizat automat de `.claude/skills/ship-changes/scripts/release.sh`.

6. **Rezultate compliance:** serviciul Go scrie scoruri/drift **direct în PostgreSQL** (`compliance_scores`, tabele drift); subiectele NATS partenere sunt doar `lokilinux.compliance.snapshot.*` (spre Go) și `lokilinux.compliance.baseline.published` (de la Go către subscriberul intern baseline). Vechea schemă „drift/score result events” nu mai există.

---

## Testare și verificare

Suite-ul de teste din `tests/` folosește `testcontainers` pentru a porni un container `timescale/timescaledb:2.28.1-pg17`, rulează Alembic la `head`, și override-uiește dependențele DB/cache/NATS/auth cu fakes in-memory (`FakeCache`, `FakeNats`). Fiecare test primește o sesiune DB cu SAVEPOINT — rollback după fiecare test, baza rămâne curată.

**Structură:**

- `tests/unit/` — 44 suite-uri (printre care `test_agent_service`, `test_job_service`, `test_alert_service`, `test_policy_service`, `test_policy_scheduler`, `test_remediation_service`, `test_report_service`, `test_complianceascode_importer`, `test_agent_install` + suite-uri observability/incidents/correlation).
- `tests/integration/` — 17 suite-uri (printre care routerele jobs, servers, policies, alerts, cves, compliance dashboard/baselines/reports + endpooint-urile noi).

**Rulare:**

```bash
cd backend
pytest -q
```

Necesită Docker daemon disponibil pentru testcontainer și setările din `backend/.env`.
