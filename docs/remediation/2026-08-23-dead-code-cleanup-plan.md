# Plan Remediere — Curățare Dead Code LokiLinux

- **Data:** 2026-08-23
- **Sursă:** Dead Code & Unused Symbols Audit complet (backend Python, agent Go, compliance Go, frontend Nuxt, cross-cutting)
- **Obiectiv:** Eliminarea codului mort / simbolurilor neutilizate / configurațiilor fără consumer **fără nicio modificare de comportament funcțional**.
- **Regulă de aur:** Nimic nu se șterge fără dovezi de referențiere zero (toate formele: import direct/indirecțional, dynamic dispatch, string-keyed registries, NATS subjects, wire contracts). Elementele < 95% confidence NU se șterg automat — intră în REVIEW.

---

## Reguli generale

1. O singură categorie de modificări pe commit; fiecare fază se termină cu verificare verde.
2. **NU se ating:** migrațiile existente (istoric aplicat), API-urile folosite de scripturi shell (`/agent/install.sh`, `/agent/download`, `/agent/download-latest`), contractul NATS live (`lokilinux.compliance.snapshot.*`, `lokilinux.compliance.baseline.published`, `lokilinux.compliance.hashes.reported`), `.certs/` + `certs/`, `agent/bin/lokilinux-agent*` versiunea curentă (0.35.3).
3. Verificare standard după fiecare fază:

```bash
make agent-test          # go test ./... -race (agent)
make compliance-test     # go test ./... -race (compliance)
cd backend && pytest     # sau comanda existentă din repo
cd backend && ruff check lokilinux && mypy lokilinux   # dacă sunt instalate
cd frontend && npm test && npm run build
```

4. Repo-ul **nu are CI** — toate suitele rulează manual; după cleanup se recomandă un workflow minim lint+test.

---

## Faza 1 — Ștergeri zero-risc (P0)

Estimat: ~450 linii Go, ~60 linii TS/CSS, 14 PNG.

### 1.1 Agent Go

| Acțiune | Fișier | Simboluri |
|---|---|---|
| DELETE fișier întreg | `agent/internal/modules/metrics.go` | `MetricsCollector`, `NewMetricsCollector`, `Collect`, `cpuUsage`, `readCPUStat`, `readLoadAvg` (99% dead — Manager nu-l instanțiază; health real = `CollectHealth`) |
| DELETE fișier întreg | `agent/internal/communication/heartbeat_manager.go` | `HeartbeatManager`, `NewHeartbeatManager`, `HeartbeatSender` (95% dead; ⚠️ decizie: dacă refactorul "Val 3" mai e plănuit, păstrează — altfel șterge) |
| DELETE director | `agent/gen/proto/` | pachet protoc-generated importat de zero fișiere; apoi `go mod tidy` (elimină `google.golang.org/protobuf` din go.mod) |
| DELETE metode+structuri | `agent/internal/storage/sqlite.go` | `EnqueueJob:92`, `UpdateJobStatus:104`, `PendingJobs:113`, `SetConfig:146`, `GetConfig:155`, `UpsertPackagesCache:178`, `GetPackagesChecksum:204`, structurile `Job:83`, `CachedPackage:169` |
| DELETE field | `agent/internal/modules/vulnerability.go` | `Vulnerability.CvssScore` (:5) |
| DELETE field | `agent/internal/modules/package_manager.go` | `Package.InstalledAt` (:27) |
| FIX comentarii înșelătoare | `agent/internal/communication/grpc_client.go` | :145, :155 (menționează HeartbeatManager care nu e pornit niciodată) |

### 1.2 Backend Python

| Acțiune | Fișier | Simboluri |
|---|---|---|
| DELETE funcție | `backend/lokilinux/db.py:50` | `get_db` (duplicat — toate 170 referințe rezolvă spre `dependencies.get_db`) |
| DELETE metode | `backend/lokilinux/services/plugin_service.py` | `validate_manifest` (:193), `compute_checksum` (:198) |
| DELETE metodă | `backend/lokilinux/services/cve_service.py:23` | `get_agent_vulnerabilities` (routerul are query propriu, cves.py:443) |
| DELETE clase schema | `backend/lokilinux/schemas/baseline.py` (~:93), `schemas/common.py` (`ErrorResponse` + re-export în `schemas/__init__.py:9,32`), `schemas/job.py:82` (`JobListResponse`), plus `PolicyListResponse`, `AgentListResponse`, `VulnerabilityListResponse` | aliasuri fără niciun importator |

### 1.3 Frontend Nuxt

| Acțiune | Fișier | Detalii |
|---|---|---|
| DELETE funcție | `frontend/server/utils/session.ts:8` | `requireSession` (0 apeluri; `getSession` rămâne) |
| DELETE tip | `frontend/types/workflow.ts:167` | `ValidationResult` (0 referințe; duplicat al `LocalValidationResult`) |
| DELETE CSS | `frontend/assets/css/global.css` | `.section-title` (:231), `@keyframes fade-in/slide-down/scale-in/slide-up` (:336-354), `.animate-stagger` (:356-369). ⚠️ fișier are WIP necommitat — nu atinge liniile noi (donut central-label vars :419+) |
| DELETE assets | `frontend/*.png` (14 buc.) | before.png, after.png, after2.png, annot.png, btn_dark.png, btn_light.png, fixed1.png, fresh_after.png, local_login.png, navcheck.png, newpalette_light.png, pkg1.png, reload.png, repro1.png |
| Un-export | `frontend/stores/dashboard.ts` | `loadSummary`, `loadTrends`, `trendsError` scoase din return object (rămân private, sunt vii intern) |
| Un-export | `frontend/stores/workflow.ts` | `baseContentHash`, `validateRemote` idem |
| DELETE action | `frontend/stores/compliance.ts:987` | `fetchAssessment` (+ export :1025) |

### 1.4 Compliance Go

| Acțiune | Fișier | Simboluri |
|---|---|---|
| DELETE metodă | `services/compliance/internal/storage/postgres.go:772` | `CountBaselineEffective` (debug leftover) |
| DELETE constantă | `services/compliance/internal/drift/detector.go:18` | `ComparedAgainstDesiredState` |
| DELETE field | `services/compliance/internal/ingest/ingest.go:67` | `Result.DriftDetected` |
| DELETE fields | `services/compliance/internal/baseline/resolver.go:37` | `Effective.AgentID` |
| DELETE fields | `services/compliance/internal/storage/postgres.go:662,666` | `PublishedBaseline.BaselineID`, `.PublishedAt` (+ trunchiază SELECT la :675) |

### 1.5 Artefacte locale (disk, NU git)

```bash
rm -rf node_modules/            # 4 KB, cache vitest accidental, fără root package.json
rm -rf graphify-out/            # 11 MB, rigenerabil
rm -rf .aislop/                 # 3 MB, snapshot worktree iulie
rm -rf banks/                   # 648 KB, mnemopi.db, 0 referințe cod
rm -rf openwiki/                # 4 KB, doar _plan.md (dacă planul nu mai contează)
```

Opțional după confirmare că nu există branch WIP: prune `.claude/worktrees/` (**1.3 GB**).
`agent/bin/`: prune DOAR versiuni vechi (0.2.0, 0.35.1, 0.35.2); păstrează 0.35.3 — sursă live pentru download endpoints.

**Verificare fază 1:** toate cele 4 suite verzi + build frontend reușit.

---

## Faza 2 — Dependencies

| Fișier | Acțiune | Dovezi |
|---|---|---|
| `backend/pyproject.toml` | REMOVE `PyJWT==2.13.0`, `protobuf==6.33.5`, `python-multipart==0.0.32`, `orjson==3.11.9` | 0 imports (auth = token opac via Better Auth get-session; codec JSON gRPC; 0 Form/File; 0 orjson) |
| `backend/pyproject.toml` (dev) | REMOVE `grpcio-tools` | Makefile `proto` folosește protoc de sistem |
| `backend/Dockerfile` | Înlocuiește pin-urile duplicate cu `pip install .` din pyproject | repară: drift `cryptography==49.0.0` vs pyproject `46.0.3` + **lipsa PyYAML** (curated_rules_loader îl importă la boot; merge azi doar prin pull tranzitiv) |

**Verificare fază 2:** rebuild imagine backend + smoke test `/health`; `go mod tidy` agent fără diff în go.sum neașteptat.

---

## Faza 3 — Configurații moarte

### 3.1 docker-compose.yml + .env.example

Șterge variabilele fără niciun consumer (verificate prin grep pe toate componentele):

- Din compose: `CA_KEY_PATH` (api+grpc), `PLUGIN_DIR` (api) + volume mount `plugins_dir` dacă se decide, `API_HOST`/`API_PORT`.
- Din `.env.example` (bulk): `TIMESCALE_*`×5, `PGBOUNCER_HOST/PORT`, `AGENT_HEARTBEAT_INTERVAL/TIMEOUT`, `AGENT_MAX_OFFLINE_DAYS`, `AGENT_REGISTRATION_TOKEN_TTL` (⚠️ exemplu spune 3600, codul hardcodează 86400 — documentează valoarea reală), `CVE_FEED_UPDATE_INTERVAL/SOURCES`, `NVD_API_KEY`, `LOG_FORMAT`, `SMTP_*`×6, `SLACK_*`×2, `BACKUP_*`×2, `S3_*`×6, `DEBUG`, `RELOAD_ON_CHANGE`, `CERT_RENEWAL_DAYS`, `PLATFORM_NAME`, `PLUGINS_ENABLED/SANDBOX_MODE/MAX_MEMORY_MB/MAX_CPU_CORES`.

Notă: SMTP/Slack/S3 nu sunt feature-uri moarte — s-au mutat în settings DB (`notifications.*`). Template-ul doar n-a fost tuns.

### 3.2 Agent config (`internal/config/config.go` + template)

Sincronizează ÎNTOTDEAUNA struct + `install_agent.sh.tmpl:88-113` în același commit:

- DELETE câmpuri: `Platform.URL` (doar loki-cli.sh îl citește ca text — păstrează în YAML, scoate din struct SAU documentează), `Heartbeat.TimeoutSec`, `Heartbeat.RetryBackoffMax` (backoff hardcodat manager.go:76 — valoarea operatorului e ignorată silențios), `Cache.Enabled/Path/RetentionDays`×3, `JobExecution.MaxParallelJobs` (jobs unbounded goroutines), `JobExecution.SandboxEnabled`, `Logging.Output`.

### 3.3 Compliance config

- DELETE secțiunea `BaselineConfig` întreagă (`config.go:39-44`) — serviciul nu publică baseline-uri.
- `Database.MaxOpenConns` (:27): WIRE (plumb `pool.Config().MaxConns`) SAU DELETE — acum e buton decorativ.
- FIX `LOG_LEVEL`: compose îl setează pentru compliance dar binarul nu-l citește → adaugă `envOr("LOG_LEVEL", cfg.Logging.Level)` la newLogger.

### 3.4 Backend Settings

- DELETE din `config.py`: `grpc_port` (:32), `better_auth_secret` (:37), `log_level` (:43) + curăță docstring-urile stale JWKS din `main.py`/`config.py`/`jwks_validator.py`.
- `better_auth_admin_token` (:54): **NU șterge** — investighează întâi (posibil security gap: proxy-ul admin către Better Auth merge fără token).

**Verificare fază 3:** `docker compose config` valid; deploy dev; agent nou instalat prin tmpl se conectează; healthcheck compliance verde.

---

## Faza 4 — Endpoint-uri moarte + clustere frontend asociate

Toate confirmate din ambele părți (0 apelanți frontend + 0 teste + 0 scripturi):

| Rută | Handler | Acțiune |
|---|---|---|
| POST `/api/v1/alerts/rules` | alerts.py:77 | DELETE (GET twin e TEST_ONLY — decidă dacă rămâne) |
| GET+POST `/api/v1/compliance/policy-assignments` | policy_engine.py:611,624 | DELETE |
| POST `/api/v1/compliance/policy-sets/{id}/rules` | policy_engine.py:519 | DELETE |
| GET `/api/v1/compliance/rules/{id}/coverage` | policy_engine.py:235 | DELETE |
| GET `/api/v1/compliance/rules/{id}/remediation-templates` | policy_engine.py:264 | DELETE |
| DELETE `/api/v1/plugins/{plugin_id}` | plugins.py:73 | DELETE handler + `PluginService.uninstall_plugin` + publish `PLUGIN_UNINSTALL` (publică către nimeni) |
| DELETE `/api/v1/categories/{category_id}` | categories.py:58 | DELETE |
| DELETE `/api/v1/projects/{project_id}` | categories.py:97 | DELETE (nu confunda cu ansible-projects delete) |
| GET `/compliance/agents/{id}/inventory/{domain}` (+ `/history`) | routers/compliance/inventory.py | DELETE + cluster store frontend: `stores/compliance.ts` fetchInventorySnapshot (:428), fetchInventoryHistory (:441), state inventorySnapshot/inventorySnapshotError/inventoryHistory (:423-425), tipuri InventorySnapshot/InventoryDelta (:32,:41) |
| GET `/api/v1/workflows/schema` | workflows.py:42 | UNKNOWN — ține până decidem despre consumatori externi/OpenAPI |

**Verificare fază 4:** suite + navigare manuală pe paginile afectate (alerts, plugins, compliance).

---

## Faza 5 — Legacy DB (necesită aprobare separată + verificare date în prod)

Modele ORM fără consumers, tabelele aferente create în migrația 001 și niciodată atinse apoi. Precedent există (migrația 029 drop dead column). Se scrie O migrație NOUĂ (030+); migrațiile existente NU se ating.

| Model | Tabelă | Decizie |
|---|---|---|
| `models/audit.py` UserProfile, RoleAssignment, UserRole | `user_profiles`, `role_assignments` | DROP după verificare că nu conțin date valoroase (pre-BetterAuth) |
| `models/cve.py:92` PackageVulnerability | tabela din 001:140-156 | DROP — înlocuită de pipeline AgentVulnerability (migr. 021, 027) |
| `models/agent.py:134` AgentMetrics | hypertable cu compresie | INVESTIGATE — zero scriitori/cititori oriunde; decide drop vs activare |
| `models/rule_evaluation.py:38` ComplianceScore (ORM) | `compliance_scores` VIE (scrisă de Go postgres.go:595) | KEEP clasa pt. metadata alembic SAU șterge clasa și păstrează tabela |
| `models/compliance_rule_resource.py` (ORM) | tabelă vie prin raw SQL | KEEP sau unifică loader-ul pe ORM |
| SQLite `jobs`, `packages_cache`, `agent_config` (sqlite.go:18-42) + indexe | scheme locale agent | REVIEW — drop din schema on-disk (PurgeExpiredJobs devine no-op altfel) |
| `file_integrity_ignores` (migr. 017) | citită de Go, ZERO scriitori | Feature pe jumătate livrat — adaugă suprafață de management (issue nou), nu șterge |

---

## Faza 6 — Docs & scripturi

| Element | Acțiune |
|---|---|
| `docs/arhitecture/` (dir typo, TRACKED) | RETIRE: mută ce valorează în `docs/architecture/` (canonicul nou), fixează pointerul greșit din `docs/compliance/03-AGENT-PLUGIN-SDK.md:6` (citează `docs/plugin-sdk/` inexistent), apoi șterge restul. 0 referințe tracked oriunde (inclusiv git -S gol). NU mass-delete fără sign-off — docs plătite |
| `scripts/rebuild.sh` | DELETE (referențiat nicăieri; divergent de init-certificates.sh) SAU integrare în `make rebuild` |
| `scripts/install-agent.sh` | **BROKEN**: scrie schema YAML pe care agentul NU o parsează (`platform_url`, `grpc.host`... ≠ schema din `install_agent.sh.tmpl:88-113`) → enrol offline crapă la dial. FIX (thin fetcher al `/api/v1/agent/install.sh`) sau DELETE cu decizie explicită pe path-ul airgap |
| Unit systemd triplicat | Single-source: `loki-cli.sh:96-121` ≡ `install_agent.sh.tmpl:134-158` ≡ install-agent.sh (drift: linia Documentation=) |
| plugin-sdk sample (docs) | Marcare explicită "design-only, never implemented" sau ștergere — SDK-ul nu are loader real (plugin flow = DB row + PLUGIN_INSTALL job + sha256 place-file) |

---

## Faza 7 — Consolidări duplicate (refactor ușor, NU automat)

1. **Pagination boilerplate ×~16 routere** (cves.py:111, jobs.py:62, servers.py:82, policies.py:54, workflows.py:71/175/278, toate 10 compliance/*) → extrage helper în `api/v1/routers/_common.py`. Cel mai mare câștig DRY al repo-ului.
2. `_safe_uuid` duplicat cross-importat: `baseline_service.py:235` ≡ `remediation_service.py:440` → hoist în utils.
3. `TriggerType` enum ×3 (schemas/policy.py, schemas/remediation.py, schemas/workflow.py — toate importate de policies.py) → un singur canon.
4. `formatBytes` frontend: unify `utils/formatBytes.ts` cu copia locală din `server/MetricsCards.vue` (param `nullText`).
5. `AgentStatus` enum ×2 (models/agent.py:19 vs schemas/server.py:14) — REVIEW, pattern FastAPI comun.
6. Harta domenii→categorie scoring Go↔Python (scoring.go:11 ≡ report_service.py:40, identică 18/18) — **DELiberat documentat, KEEP**; adaugă test de paritate ca să prindă divergența la adăugarea unui domeniu.

---

## Faze separate (decizii de design — NU parte din cleanup)

| Subiect | Stare | Opțiuni |
|---|---|---|
| `proto/lokilinux.proto` | ficțiune de design: doar HeartbeatStream implementat; wire real = hand-written JSON structs (gen/lokilinux) cu câmpuri absente din proto (`domain_hashes`, `resync_domains`, `timeout_seconds`); PlatformService + ReportMetrics/SyncPolicy paper-only | Rewrite onest din structurile hand-written sau regenerare completă |
| `WORKFLOW_STEPS` job type | Executor complet + testat pe agent, backend nu trimite niciodată tipul (forward-compat deliberat, manager.go:412-421) | Păstrează până la decizia roadmap |
| Branch-uri `responseToMap` policy/reboot/plugin_action (grpc_client.go:353-361) + câmpurile gen aferente | Server nu le populează niciodată | Șterge branch-urile SAU implementează handling |
| `nats_topics.py:33-34` COMPLIANCE_DRIFT_DETECTED / COMPLIANCE_SCORE_UPDATED | Contract documentat (04-PROTOCOL §4), implementat de nimeni: Go nu publică nimic, backend nu subscribe-uiește | Implementează publish-urile SAU șterge constantele + corectează docs |
| Metrics port 9091 compliance | Servit dar nescrapat în topology compose (k8s-forward per docs 13-OPS) | Expune + scraper SAU acceptă |
| `settings_schema.py` ~15 key-uri storage-only | Editabile în UI, stocabile în DB, fără efect backend | Documentate self-aware — hide-from-UI sau wire |
| CI/CD inexistent | Toate suitele rulează doar manual | Workflow minim lint+test — recomandat imediat după faza 1 |

---

## Anexe

### A. Ce s-a verificat și e VIU (nu se re-auditează)

Backend: toți 15 workers porniți (main.py:86-137), toate 17 routere + 10 compliance subrouters înregistrate, report_service complet viu (serializatoare string-keyed `_SERIALIZERS`:435), workflow compiler/engine intern viu, RedisCache 12/12 metode, auth trio (111/55/112 refs), RateLimitMiddleware, croniter/openpyxl/reportlab/cryptography/structlog/httpx/grpcio/nats-py folosite real.
Agent: main.go complet viu, jsonCodec load-bearing, toți cei 14 executori non-metrics disparați din switch (manager.go:422-469) și trimiși de backend (matrice job-type în audit), registry 24/24 colectori (collector.go:43-66), logbuffer (contract slogHandler), systemd_run, canonical hashing.
Compliance: tot restul pachetelor atins din main.go; contractele NATS LIVE verificate bidirecțional; toate tabelele scrise de Go sunt citite de backend (except cele notate în faza 5).
Frontend: toate 60 componente folosite, toate 33 rute accesibile (tabel reachability în audit), toate 13 store-uri instanțiate, toate exports din composables/utils folosite (except cele din faza 1), deps package.json toate ≥1 referință.
Lanț alembic: LINIAR, un singur head (029). Lipsa lui 014 = gap cosmetic de numerotare (015.down_revision="013") — nu "repara" nimic acolo.

### B. Observații de securitate (informational, nu dead code)

1. `certs_dir` volume (conține `ca.key`) montat read-only în lokilinux-api care nu are nevoie de cheia CA.
2. `better_auth_admin_token` definit dar proxy-ul admin merge fără token — posibil security gap (faza 3.4).
3. `frontend/.env` local conține parole reale — ne-trackuit (gitignore ok), igienă locală.

### C. Istoric / proveniență

Audit efectuat static (5 agenți paraleli, grep + dependency analysis + contract matrices NATS/gRPC/HTTP), fără execuție de cod. Confidence ≥ 90% pe toate elementele SAFE_TO_DELETE; fiecare element are dovezile enumerate în raportul de audit din sesiunea 2026-08-23.
