# LokiLinux Backend — Arhitectură și fluxuri

Acest document descrie backend-ul LokiLinux: limbajul, framework-urile, topologia de runtime, modul în care cererile REST, joburile, heartbeat-urile agentului și datele de compliance se deplasează prin sistem, și diagramele ASCII corespunzătoare. Este complementar documentației full-stack din [`../README.md`](../README.md) și [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) — pentru detalii despre frontend sau arhitectura generală, consultați acele fișiere.

**Clasificare arhitecturală.** Implementarea este un **modular monolith / layered hybrid** în Python `>=3.11` cu FastAPI: routere de feature pe domenii, servicii partajate de business logic, modele ORM SQLAlchemy, scheme Pydantic și workeri de fundal in-process. Nu este o arhitectură hexagonală pură — câteva routere read-only (de ex. `servers`, `categories`) interoghează SQLAlchemy direct, în timp ce serviciile dețin majoritatea căilor de scriere și mașinilor de stare.

**Două procese de runtime din același cod.** Un singur codebase este deployat ca două procese separate din aceeași imagine Docker:

- `uvicorn lokilinux.main:app --host 0.0.0.0 --port 8000 --workers 2` — serverul REST + 11 workeri NATS/asyncio pe portul `:8000`.
- `python -m lokilinux.grpc_server` — serverul gRPC pentru comunicarea cu agenții Go, pe portul `:50051` cu mTLS reciproc.

Serviciul Go `lokilinux-compliance` (`services/compliance/`) este un participant extern, conectat prin NATS și PostgreSQL — **nu** un pachet Python în backend.

---

## Tehnologii și componente

| Componentă | Versiune / pachet | Rol |
|---|---|---|
| Python | `>=3.11` (3.11.15-slim în Docker) | Runtime |
| FastAPI | 0.138.1 | Framework HTTP async |
| Uvicorn | 0.49.0 | Server ASGI |
| Pydantic / Pydantic Settings | 2.13.4 / 2.14.2 | Validare scheme + configurare din mediu |
| ORJSON | 3.11.9 | Serializer JSON rapid |
| SQLAlchemy async | 2.0.51 | ORM cu session async |
| psycopg | 3.3.4 (async + binary) | Driver PostgreSQL |
| Alembic | 1.18.5 | Migrații de schemă (001→024) |
| PostgreSQL / TimescaleDB | 2.28.1-pg17 | Stocare principală + serie temporală |
| pgBouncer | 1.25.2-p0 | Connection pooling (port 6432) |
| Redis | 7.4.9 (hiredis) | Cache-aside, rate-limit, enrollment tokens |
| NATS | 2.15.0 (nats-py) | Bus de evenimente; serverul Compose pornește cu JetStream (`--js`), dar codul Python folosește API-urile standard subject publish/subscribe |
| grpcio | 1.81.1 | Server gRPC pentru agenți (JSON codec) |
| httpx | 0.28.1 | Client HTTP pentru Better Auth session validation |
| structlog | 26.1.0 | Logging structurat |
| croniter | 6.2.4 | Scheduling policy pe expresii cron |
| openpyxl / reportlab | 3.1.5 / 5.0.0 | Export compliance XLSX/PDF |

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
                         | FastAPI + 11 workers        |
                         +------+-----------+----------+
                                |           |
                                |           +--> Redis :6379
                                +--------------> NATS :4222
                                |
                                v
                         pgBouncer :6432
                                |
                                v
                     PostgreSQL/TimescaleDB :5432

Go Linux agents -- mTLS HeartbeatStream --> +------------------------+
                                            | lokilinux-grpc :50051  |
                                            | separate Python process|
                                            +----+------+------------+
                                                 |      |
                                                 +--> Redis/NATS
                                                 +--> pgBouncer -> PostgreSQL

NATS :4222 <--> lokilinux-compliance (Go) -----> PostgreSQL/TimescaleDB
```

Ambele procese Python (API și gRPC) își creează propriile conexiuni la DB/cache/NATS — nu împart clienți. Agenții se conectează exclusiv la procesul gRPC separat. Compliance este integrat prin NATS și baza de date partajată, nu prin apel Python direct.

### Porturi și servicii Compose

| Serviciu | Port(uri) | Descriere |
|---|---|---|
| `lokilinux-api` | `8000:8000`, `9090:9090` | REST FastAPI; mapping-ul 9090 este present în Compose dar **nu există** o rută Prometheus `/metrics` definită în sursa backend curentă |
| `lokilinux-grpc` | `50051:50051` | Server gRPC Python, JSON codec, mTLS |
| `lokilinux-migrate` | — | One-shot: `alembic upgrade head` |
| `lokilinux-compliance` | niciun port public | Go microservice (drift/baseline/scoring) |
| `lokilinux-frontend` | `3000:3000` | Nuxt 4 |
| `postgres` | intern `5432` | TimescaleDB |
| `pgbouncer` | `6432:5432` | Connection pool |
| `redis` | `6379:6379` | Cache |
| `nats` | `4222:4222` (client), `8222:8222` (monitor) | Bus evenimente cu JetStream |

---

## Structura codului

```text
backend/
├── lokilinux/
│   ├── main.py               # FastAPI assembly, lifespan, middleware, health, /downloads, /api/v1
│   ├── config.py             # Settings (env) — DATABASE_URL, BETTER_AUTH_URL, etc.
│   ├── settings_schema.py    # Platform settings (DB-backed, group.key)
│   ├── db.py                 # Async engine + session factory + get_db dependency
│   ├── cache.py              # RedisCache cache-aside + TTL constants
│   ├── dependencies.py       # get_db, get_cache, get_nats (request-scoped)
│   ├── nats_topics.py        # Single source of truth pentru subjecte NATS
│   ├── grpc_server.py        # Bootstrap gRPC: JSON codec, mTLS, port 50051
│   ├── install_agent.sh.tmpl # Template installer agent (rendered de /agent/install.sh)
│   ├── api/v1/
│   │   ├── __init__.py       # Router aggregator + prefixe
│   │   └── routers/          # Routere feature (dashboard, jobs, servers, etc.)
│   │       └── compliance/   # Sub-routere compliance (baselines, drift, inventory, etc.)
│   ├── api/grpc/
│   │   └── agent_service.py  # AgentServicer — HeartbeatStream bidirecțional
│   ├── auth/
│   │   ├── jwks_validator.py # get_current_user — delegare Better Auth session
│   │   └── dependencies.py   # require_role, safe_user_uuid
│   ├── middleware/
│   │   └── rate_limit.py     # Rate limit Redis-backed, fail-open
│   ├── models/               # Modele ORM SQLAlchemy (28 fișiere)
│   ├── schemas/              # Scheme Pydantic (request/response)
│   ├── services/             # Logică de business (17 fișiere)
│   └── workers/              # Consumatori NATS + bucle asyncio (11 workeri)
├── alembic/                  # Migrații 001 → 024
├── tests/
│   ├── conftest.py
│   ├── unit/                 # 9 suite-uri unitare
│   └── integration/          # 8 suite-uri de integrare
├── pyproject.toml
├── Dockerfile                # Production: uvicorn --workers 2
├── Dockerfile.dev            # Development: uvicorn --reload
└── alembic.ini
```

### Responsabilități pe modul

| Modul | Rol |
|---|---|
| `main.py` | Assembly FastAPI: `lifespan()` (engine, cache, NATS, 11 workeri), middleware (CORS, GZip, rate-limit, request-id), health probes (`/health`, `/ready`), mount `/downloads` (pachete agent), `/api/v1`, validation handler → 422 |
| `config.py` | `Settings(BaseSettings)` — configurare din variabile de mediu: `database_url`, `redis_url`, `nats_url`, `grpc_port`, `better_auth_url`, `better_auth_secret`, `agent_cert_dir`, `frontend_url`, `platform_url`, `agent_version`, `agent_package_dir` |
| `settings_schema.py` | Platform settings stocate în tabelul `settings` (`group.key`), separate de `config.py` care citește din mediu; `get_setting_value()` cu cast per-tip; chei secrete mascate |
| `db.py` / `dependencies.py` | `build_engine()` (pool_size=20, max_overflow=10, pool_recycle=3600, pool_pre_ping), `build_session_factory()` (autoflush=False), `get_db()` cu commit pe succes / rollback pe excepție, `get_cache()` și `get_nats()` din `app.state` |
| `api/v1/` | Routere montate la `/api/v1`: `/dashboard`, `/categories` (fără prefix), `/compliance/*`, `/servers`, `/jobs`, `/vulnerabilities`, `/policies`, `/plugins`, `/playbooks`, `/playbook-templates`, `/ansible-roles`, `/ansible-projects`, `/alerts`, `/admin`, `/agent` (install/packages/download), `/agents/register`. Auth Better Auth nu se aplică pe `/health`, `/ready`, `/agent/install.sh`, `/agent/download-latest`, `/agent/download` (cu token enrollment), și `/agents/register` (cu token enrollment) |
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
4. **13 workeri** porniți după ce NATS este disponibil:
   - `JobExecutorWorker`, `CVEProcessorWorker`, `AlertProcessorWorker`, `PolicyWorker`, `PolicySchedulerWorker`, `PluginWorker`, `HeartbeatMonitorWorker`, `JobTimeoutWorker`, `RetentionCleanupWorker`, `RemediationSchedulerWorker`, `RemediationVerificationWorker`, `NotificationWorker`, `CVEEnrichmentWorker`.
5. **Servește cereri.**
6. **Shutdown** — ordine inversă: `stop()` explicit pe `HeartbeatMonitorWorker`, `RemediationVerificationWorker`, `RemediationSchedulerWorker`, `JobTimeoutWorker`, `PolicySchedulerWorker`, `RetentionCleanupWorker`, `CVEEnrichmentWorker` (cele 7 workeri pe buclă `asyncio`, fără subscriere NATS); apoi `nc.drain()` (NATS), `cache.disconnect()` (Redis), `engine.dispose()` (DB). Ceilalți 6 workeri (`JobExecutorWorker`, `CVEProcessorWorker`, `AlertProcessorWorker`, `PolicyWorker`, `PluginWorker`, `NotificationWorker`) sunt subscriberi NATS — nu au `stop()` explicit, sunt eliberați de `nc.drain()`.

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
| `PluginWorker` | `lokilinux.plugin.install` | Instalare plugin-uri |

**Bucle asyncio:**

| Worker | Interval | Rol |
|---|---|---|
| `PolicySchedulerWorker` | 30s | Atomic claim + `run_policy()` pentru policy-uri cu trigger cron |
| `HeartbeatMonitorWorker` | 60s | Sweep joburi ACTIVE stale → publică `lokilinux.agent.unhealthy` |
| `JobTimeoutWorker` | 60s | Marchează joburi non-terminale depășite ca `TIMEOUT` |
| `RemediationSchedulerWorker` | 30s | Dispatch joburi de remediere aprobate în ferestre de mentenanță |
| `RetentionCleanupWorker` | 3600s | Purjare audit log conform politicii de retenție |

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
- **Rezultate compliance** de la Go: `lokilinux.compliance.drift.detected`, `lokilinux.compliance.score.updated`, `lokilinux.compliance.baseline.published` — consumate de workeri Python pentru WebSocket push / invalidare cache.

### Persistență

Modelele ORM din `lokilinux/models/` acoperă:

- **Agenți și inventar:** `Agent`, `AgentHealth`, `AgentMetrics`, `AgentStatus`, `InventoryBlob`, `InventoryDelta`, `InventorySnapshot`
- **Joburi:** `Job`, `JobResult`, `JobStatus` (enum)
- **CVE / pachete / vulnerabilități:** `CVE`, `Package`, `PackageVulnerability`, `AgentVulnerability`
- **Policy / audit:** `Policy`, `PolicyAudit`, `AuditLog`, `Setting`, `UserProfile`, `UserRole`, `RoleAssignment`
- **Compliance:** `Baseline`, `BaselineApproval`, `BaselineEffective`, `BaselineVersion`, `ComplianceRule`, `PolicyAssignment`, `PolicySet`, `PolicySetRule`, `RemediationTemplate`, `ComplianceScore`, `RuleEvaluation`, `DriftDetail`, `DriftEvent`, `FileChange`, `FileHash`, `ComplianceReport`
- **Remediere:** `MaintenanceWindow`, `RemediationAction`, `RemediationJob`, `RemediationPlan`
- **Ansible / playbooks:** `AnsibleRole`, `AnsibleProject`, `Playbook`, `PlaybookTemplate`
- **Plugin-uri:** `Plugin`, `PluginInstallation`, `PluginStatus`
- **Altele:** `Category`, `Project`, `Alert`, `AlertRule`

`alembic/env.py` importă `lokilinux.models` (toate modelele înregistrate pe `Base.metadata`), citește `Settings.database_url`, și rulează `alembic upgrade head`. **Nu există un strat repository/DAO separat** — serviciile accesează sesiunea SQLAlchemy direct.

Migrații: 24 fișiere (`001_initial_schema` → `024_jobs_policy_id_set_null`).

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

1. **Autentificare:** codul curent apelează `GET {BETTER_AUTH_URL}/api/auth/get-session` pentru validare sesiune, în ciuda referințelor „JWKS” / „RS256” din comentariile `config.py`. `BETTER_AUTH_SECRET` este cerut de `Settings` și Compose, dar backend-ul nu-l folosește pentru semnare sau verificare locală de token-uri.

2. **gRPC codec:** serverul gRPC curent folosește **JSON serializers** (`json.dumps`/`json.loads` cu `SimpleNamespace`). Fișierul `../proto/lokilinux.proto` există la nivel de repository ca referință de schemă, dar wire-ul runtime nu folosește protobuf binary.

3. **Workeri:** `main.py` pornește curent **11 workeri** (inclusiv `RemediationSchedulerWorker`). Nu repetați rezumatele învechite de „10 workeri”.

4. **Port 9090 / Prometheus:** Compose expune portul `9090` pentru `lokilinux-api`, dar **nu există** o rută `/metrics` definită în sursa backend curentă. Nu confundați `/servers/{agent_id}/metrics` (endpoint de date pentru metricile agentului) cu un endpoint Prometheus.

5. **Versiune agent:** `config.py` definește `agent_version: str = "0.1.0"` ca default, în timp ce Compose setează `AGENT_VERSION: ${AGENT_VERSION:-0.35.3}`. Versiunea este **configurație-driven** — sursa de adevăr depinde de contextul de deployment (env var în producție, default Python în development direct). La runtime, valoarea servită vine din DB (`settings.agent.version`, updatată de release flow); build-side SSOT este `agent/VERSION` la rădăcina repo-ului, citit de Makefile și sincronizat automat de `.claude/skills/ship-changes/scripts/release.sh`.

---

## Testare și verificare

Suite-ul de teste din `tests/` folosește `testcontainers` pentru a porni un container `timescale/timescaledb:2.28.1-pg17`, rulează Alembic la `head`, și override-uiește dependențele DB/cache/NATS/auth cu fakes in-memory (`FakeCache`, `FakeNats`). Fiecare test primește o sesiune DB cu SAVEPOINT — rollback după fiecare test, baza rămâne curată.

**Structură:**

- `tests/unit/` — 9 suite-uri: `test_agent_service`, `test_job_service`, `test_alert_service`, `test_policy_service`, `test_policy_scheduler`, `test_remediation_service`, `test_report_service`, `test_complianceascode_importer`, `test_agent_install`.
- `tests/integration/` — 8 suite-uri: `test_jobs_router`, `test_servers_router`, `test_policies_router`, `test_alerts_router`, `test_cves_router`, `test_compliance_dashboard_router`, `test_compliance_baselines_router`, `test_compliance_reports_and_actions`.

**Rulare:**

```bash
cd backend
pytest -q
```

Necesită Docker daemon disponibil pentru testcontainer și setările din `backend/.env`.
