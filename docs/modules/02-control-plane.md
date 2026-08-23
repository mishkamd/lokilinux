# 02 — Control Plane (Backend FastAPI)

> Documentație generată din cod la commit `77c4220` (v0.3.0), august 2026.

## Rol

Control Plane este creierul platformei LokiLinux: expune API-ul REST consumat de frontend, primește heartbeaturile de la agenții Go prin gRPC mTLS, orchestrează job-urile (patch management, Ansible, remediere, workflow-uri), procesează fluxurile CVE și rulează CRUD-ul pentru modulul de compliance. Nu inițiază niciodată conexiuni spre agenți — răspunde doar la heartbeat-uri.

## Tehnologii și versiuni

| Componentă | Versiune | Rol |
|---|---|---|
| Python | 3.11 | Runtime |
| FastAPI | 0.138.1 | REST framework + ASGI |
| uvicorn | — | Server ASGI |
| SQLAlchemy [asyncio] | 2.0.51 | ORM async (prin pgBouncer, transaction mode) |
| Alembic | — | Migrări DB (`alembic upgrade head`, un-shot în container separat) |
| grpcio / grpcio-tools | 1.81.1 | Server gRPC (tools doar pentru codegen proto) |
| Pydantic | 2.13.4 | Scheme validare API |
| NATS client | — | Event bus async |
| Redis | — | Cache + invalidare |

## Compoziție

```
backend/
├── lokilinux/
│   ├── main.py               # Lifespan: NATS connect → pornire 15 workers → shutdown invers
│   ├── grpc_server.py        # Entry-point container lokilinux-grpc (python -m lokilinux.grpc_server)
│   ├── nats_topics.py        # Toate subiectele NATS, prefix „lokilinux." — sursă unică de adevăr
│   ├── api/v1/__init__.py    # Montarea routerelor sub /api/v1
│   │   └── routers/          # 15 fișiere routere REST (17 monturi) + sub-pachet compliance/ cu 9 routere
│   ├── api/grpc/agent_service.py   # Servicer gRPC AgentService (heartbeat, jobs, policy)
│   ├── auth/                 # Validare Bearer token contra Better Auth; dependențe roluri
│   ├── models/               # 26 modele SQLAlchemy ORM
│   ├── schemas/              # Scheme Pydantic (cereri/răspunsuri API)
│   ├── services/             # ~27 servicii business logic (fără HTTP)
│   └── workers/              # 15 workeri background (consumatori NATS + tickere)
├── alembic/                  # Migrările versionate
├── pyproject.toml
└── Dockerfile
```

### Straturi

Aplicația e organizată pe trei straturi, fiecare fără cunoștință despre cel superior:

1. **Routers** (`api/v1/routers/`) — parsare HTTP, autentificare, apel spre service, serializare Pydantic.
2. **Services** (`services/`) — business logic pur: `job_service` creează job-uri, `remediation_service` compilează planuri, `workflow_engine` execută graful etc.
3. **Models** (`models/`) — SQLAlchemy ORM; toate interogările trec prin `AsyncSession`.

Modele principale (`models/`): `agent`, `job`, `cve`, `policy`, `alert`, `audit`, `plugin`, `playbook`, `playbook_template`, `ansible_project`, `ansible_role`, `category`, plus familia compliance (`compliance_rule`, `compliance_framework`, `compliance_assessment`, `compliance_report`, `compliance_exception`, `baseline`, `drift`, `file_integrity`, `rule_evaluation`, `remediation`) și `workflow`.

## Suprafața publică REST (`/api/v1`)

Montare în `api/v1/__init__.py:29-45`; prefix global `/api/v1` setat în `main.py`.

| Router | Prefix URL | Endpoint-uri cheie |
|---|---|---|
| `dashboard.py` | `/dashboard` | `/summary`, `/trends` |
| `servers.py` | `/servers` | list/get agent, `/{agent_id}/packages`, `/metrics`, POST `/maintenance`, PATCH `/assignment` |
| `jobs.py` | `/jobs` | create+list, get, `/{job_id}/results`, POST `/{job_id}/approve`, DELETE |
| `cves.py` | `/vulnerabilities` | `/summary`, `/trend`, `/top-resources`, `/patchable`, `/export`, get CVE, `/{cve_id}/resources`, POST `/{cve_id}/remediate`, `/{cve_id}/accept-risk`, `/{cve_id}/rescan`, GET `/servers/{agent_id}` |
| `policies.py` | `/policies` | CRUD, POST `/{policy_id}/run`, POST `/{policy_id}/migrate` (→ Workflow), GET `/{policy_id}/audit` |
| `alerts.py` | `/alerts` | POST `/{alert_id}/acknowledge`, `/{alert_id}/resolve`, CRUD `/rules` |
| `plugins.py` | `/plugins` | POST `/{plugin_id}/install`, `/enable`, `/disable`, DELETE `/{plugin_id}` |
| `playbooks.py` | `/playbooks` | CRUD + POST `/{playbook_id}/execute` |
| `playbook_templates.py` | `/playbook-templates` | CRUD + POST `/{template_id}/launch`, GET `/{template_id}/history` |
| `ansible_roles.py` | `/ansible-roles` | CRUD (gated pe plugin-ul Ansible activ) |
| `ansible_projects.py` | `/ansible-projects` | CRUD (inventarul = flota live, prin `default_agent_ids`) |
| `agent_install.py` | `/agent` + `/agents` | GET `/packages`, GET `/install.sh`, POST `/enrollment-token`, GET `/download(-latest|-direct)`; routerul `register_router` e montat și la `/agents` (enrolare agent) |
| `admin.py` | `/admin` | GET/PUT `/agent-config`, CRUD `/users`, POST `/users/{id}/role`, GET/PUT `/settings`, GET `/settings/public`, GET `/audit` |
| `workflows.py` | `/workflows` | GET `/schema`, POST `/validate`, CRUD workflow, versionare `/versions` + publish, POST `/dry-run`, POST `/run`, GET `/runs/{run_id}`, POST `/runs/{run_id}/cancel`, approve/reject pe step |
| `categories.py` | `/categories`, `/projects` | CRUD categorii CVE + proiecte |
| `compliance/` (sub-pachet) | `/compliance/*` | vezi mai jos |

### Sub-routere compliance (`/compliance/...`)

| Fișier | Acoperire |
|---|---|
| `policy_engine.py` | CRUD `/rules`, coverage per regulă, CRUD `/policy-sets` (+ publish / archive / new-version / import), CRUD `/policy-assignments` |
| `baselines.py` | CRUD `/baselines`, versionare submit/approve/publish/rollback, GET `/agents/{id}/effective-baseline` |
| `assessments.py` | POST `/assessments` (202 async), list/get |
| `drift.py` | `/drift-events`: list/get/details, acknowledge/suppress/resolve |
| `exceptions.py` | CRUD `/exceptions` + approve/revoke |
| `file_integrity.py` | GET `/agents/{id}/file-hashes`, `/file-changes`, `/file-changes/by-path` |
| `inventory.py` | GET `/agents/{id}/inventory/{domain}`, `.../history` |
| `remediation.py` | CRUD `/maintenance-windows`, planuri de remediere: submit/dry-run/approve/execution/rollback |
| `reports.py` | POST/GET `/reports`, GET `/{report_id}/download` |

Autentificare: Bearer token validat prin delegare către sesiunea Better Auth a frontendului. Roluri: `ADMIN`, `MANAGER`, `OPERATOR`, `VIEWER`, `AUDITOR`.

## Server gRPC (`lokilinux-grpc`)

Entry-point `grpc_server.py`, servicer în `api/grpc/agent_service.py`. Port **50051**, mTLS obligatoriu (certificat server + CA din `/etc/lokilinux/certs`).

Implementează `AgentService` din `proto/lokilinux.proto`:

| RPC | Direcție | Ce face |
|---|---|---|
| `HeartbeatStream` | stream bidirecțional | Agentul trimite starea (sistem, pachete cu checksum delta SHA-256, vulnerabilități, rezultate job-uri, hash-uri domenii compliance); serverul răspunde cu job-uri pending, delta de policy și cereri de resync pe domenii |
| `ReportMetrics` | stream agent→server | Metrice bulk; ACK |
| `SyncPolicy` | request/response | Pull configurare policy după versiune |

Decizie importantă: **codec JSON peste transport gRPC** — `proto/lokilinux.proto` definește mesajele (namespace + documentație), dar firul folosește JSON sub numele de codec `"proto"` (și în agent, `grpc_client.go:23-34`). Motiv: structuri Go libere + debugging ușor. Limită mesaj: 16 MB ambele părți.

Fluxul unui heartbeat:

```
Agent (mTLS)              api/grpc/agent_service.py
    │ HeartbeatStream req       │
    ├──────────────────────────►│ upsert agent + system_info
    │                           │ delta packages după checksum
    │                           │ persistă vulnerabilități
    │                           │ publică COMPLIANCE_SNAPSHOT.* ──► NATS ──► lokilinux-compliance
    │                           │ salvează job_results primite
    │◄──────────────────────────┤
    │ resp: pending_jobs        │ get_pending_jobs() (fără cele neaprobate)
    │       update_policy       │ delta policy vs config_version
    │       resync_domains      │ domenii cerute de compliance service
```

Job-urile se execută pe agent **doar** ca răspuns la heartbeat (outbound-only). Rezultatele revin în heartbeat-ul următor.

## Workeri background (`workers/`)

15 workeri porniți în lifespan (`main.py:85-140`), opși la shutdown în ordine inversă:

| Worker | Declanșare | Rol |
|---|---|---|
| `JobExecutorWorker` | subscr. NATS | Consumează rezultate job-uri, actualizează starea |
| `CVEProcessorWorker` | subscr. NATS | Procesează evenimente feed CVE |
| `CVEEnrichmentWorker` | ticker | Îmbogățire CVE cu date suplimentare |
| `AlertProcessorWorker` | subscr. NATS | Creează alerte din evenimente |
| `NotificationWorker` | subscr. NATS | Notificări (email/SMTP configurabil) |
| `PolicyWorker` | subscr. NATS | Aplică schimbări de policy |
| `PolicySchedulerWorker` | ticker | Rulează policy-uri programate |
| `HeartbeatMonitorWorker` | ticker | Marchează agenții INACTIVE la lipsă heartbeat |
| `JobTimeoutWorker` | ticker | Sweep job-uri blocate → TIMEOUT |
| `PluginWorker` | subscr. NATS | Ciclu de viață instalare plugin-uri |
| `RemediationSchedulerWorker` | ticker | Dispatch planuri de remediere în ferestre de mentenanță |
| `RemediationVerificationWorker` | ticker | Verifică succesul remedierilor post-execuție |
| `RetentionCleanupWorker` | ticker | Curățenie date expirate |
| `WorkflowRunnerWorker` | subscr. NATS | Avansează run-uri de workflow |
| `WorkflowSchedulerWorker` | ticker | Declanșează workflow-uri programate (trigger SCHEDULE) |

## Subiecte NATS (`nats_topics.py`)

Toate cu prefix `lokilinux.`:

| Subiect | Producător → Consumator |
|---|---|
| `lokilinux.job.created` / `.result` | job_service → JobExecutorWorker |
| `lokilinux.policy.changed` / `.apply` | PolicyService → PolicyWorker |
| `lokilinux.alert.created` | AlertService → AlertProcessor/NotificationWorker |
| `lokilinux.agent.unhealthy` | HeartbeatMonitor → AlertProcessor |
| `lokilinux.cve.database.updated` | CVE sync → CVEProcessor |
| `lokilinux.plugin.install` / `.uninstall` | PluginService → PluginWorker |
| `lokilinux.compliance.hashes.reported` | servicer gRPC → compliance Go |
| `lokilinux.compliance.snapshot.{domain}` | servicer gRPC → compliance Go (ingest) |
| `lokilinux.compliance.drift.detected` | compliance Go → API workers |
| `lokilinux.compliance.score.updated` | compliance Go → API workers |
| `lokilinux.compliance.baseline.published` | API → compliance Go (invalidare baseline_effective) |

## Dependențe

- **PostgreSQL/TimescaleDB** prin pgBouncer (6432) — starea persistentă
- **NATS JetStream** — event bus intern + passthrough snapshot-uri compliance
- **Redis** — cache dashboard/trends, invalidare
- **Better Auth** (frontend Nuxt) — sursa de adevăr pentru sesiuni utilizator
- **CA intern** — semnare/verificare certificate mTLS

Dependenți: frontend Nuxt (REST), agenți Go (gRPC), lokilinux-compliance (NATS passthrough).

## Decizii de design

1. **Outbound-only agents** — serverul nu dial-ează niciodată agenții; scalabilitate și securitate (nu e nevoie de porturi deschise pe hosturile gestionate).
2. **JSON codec peste gRPC** — debugging simplu (tcpdump/logs lizibile), structuri Go fără codegen strict; swap spre proto binar documentat în cod.
3. **Event-driven** — tot ce nu trebuie sincron în request publică pe NATS; workerii separă latența API-ului de procesarea grea (CVE enrichment, notificări).
4. **Delegare auth către Better Auth** — un singur furnizor de sesiuni pentru UI și API; backendul nu stochează parole.
5. **pgBouncer transaction mode** — toate conexiunile async SQLAlchemy trec prin pool; sesiunile nu pot folosi prepared statements numite.
