# Dead Code Audit — LokiLinux

> **Status: AUDIT ONLY.** Nu s-a șters și nu s-a modificat nimic. Toate constatările de mai jos
> sunt rezultatul unor verificări statice read-only. Ștergerile se fac doar după aprobare, în
> commit-uri separate (vezi §8).

Data: 2026-10-17 · Branch: `platform-observability-hardening` · HEAD: `333e4d9`

## 1. Rezumat

Repository curat în linii mari. Majoritatea finder-urilor automate ies curate:

- **Python**: `ruff` F-rules → 15 importuri neutilizate (7 dintre ele re-exporturi intenționate).
- **Go agent**: `go vet` curat; `deadcode` (analiză whole-program) → 12 funcții inaccesibile din `main`.
- **Go compliance**: `go vet` curat; `deadcode` → 1 funcție inaccesibilă.
- **Frontend**: 0 componente/composable/store orfane; 2 dependențe candidate.
- **Infra/artefacte**: 3 worktree-uri stale (565 MB) + worktree `.aislop` pe disc (ignorate de git).

Niciun constat nu e o problemă de corectitudine — sunt cod/fișiere fără consumatori, plus câteva
configurații documentate dar neconectate. Riscul de eliminare este mic pentru majoritatea, dar
câteva sunt deliberat păstrate (deferrale `ponytail:`) și NU trebuie șterse fără context.

## 2. Scope & metodă

- **Analizate**: 846 fișiere tracked (py 363, go 172, vue 125, ts 58, sh 12, yml/yaml 13) + directoare
  ignorate relevante (`.claude/worktrees`, `.aislop`, `graphify-out`, `sbom`, `banks`, `logs`).
- **Unelte rulate** (read-only):
  - `ruff 0.15.20` — `F401,F811,F841,F822,F823` (importuri/variabile/funcții neutilizate, redefiniri).
  - `vulture 2.16` — hint de simboluri neutilizate (zgomotos pe FastAPI; folosit doar ca indiciu).
  - `golang.org/x/tools/cmd/deadcode` (`v0.30.0` @ go1.24, `v0.35.0` @ go1.25) — funcții inaccesibile.
  - `go vet ./...` (agent: go1.24; compliance: go1.25) — rulat în containere oficiale `golang`.
  - Cross-referință manuală `file:line` pentru fiecare candidat (apelanți reali, decoratori,
    registry-uri, DI, rute, teste, migrations, docs, compose).
- **Regulă**: un simbol nu e „mort" doar pentru că nu are import direct — s-au verificat
  entry-points (`main.py`, `main.go`, rute FastAPI, registry-uri NATS, plugin hooks, DI).

Toate verificările sunt reproduse în §7.

## 3. Constatări

Legendă clasificare: `SAFE_TO_DELETE`, `PROBABLY_DEAD`, `LEGACY`, `DUPLICATE`, `UNUSED_SYMBOL`,
`UNUSED_DEPENDENCY`, `DEAD_CONFIGURATION`, `UNKNOWN`.

### 3.1 Python — simboluri/importuri neutilizate

| ID | Fișier:linie | Simbol | Clasificare | Dovadă | Risc | Acțiune |
|---|---|---|---|---|---|---|
| P1 | `backend/lokilinux/services/agent_policies.py:55` | `PolicyOut` | UNUSED_SYMBOL / SAFE_TO_DELETE | Doar definiție + `.of()` intern; 0 apelanți (nici teste) | Mic | Șterge clasa |
| P2 | `backend/lokilinux/services/agent_policies.py:73` | `VersionOut` | UNUSED_SYMBOL / SAFE_TO_DELETE | Idem P1 | Mic | Șterge clasa |
| P3 | `backend/lokilinux/schemas/baseline.py:91` | `BaselineApprovalResponse` | PROBABLY_DEAD | Doar definiție; 0 referințe încod | Mic–Mediu | Verifică dacă nu e consumat extern (OpenAPI/SDK) înainte |
| P4 | `services/agent_policies.py:18,394`; `services/agent_policy_compiler.py:215`; `services/job_service.py:367,368`; `kms/file_provider.py:14`; `api/v1/routers/cves.py:38`; `api/v1/routers/compliance/exceptions.py:11` | 8 importuri | UNUSED_SYMBOL / SAFE_TO_DELETE | `ruff F401` | Mic | Șterge importurile (auto-fix `ruff --fix` posibil) |
| P5 | `services/agent_policy_compiler.py:134` | `if "interval_seconds" in heartbeat or True:` | LEGACY (bug de calitate) | `vulture` 100% — condiția e mereu adevărată; ramura `in` moartă | Mic | Curăță condiția (`or True` = cod mort logic) |

Importurile P4 exacte (ruff F401, excluzând re-exporturile intenționate din `models/__init__.py:36-42`):
`datetime` (exceptions.py), `VulnerabilityStatus` (cves.py), `lru_cache` (file_provider.py),
`Any` + `postgresql.insert` (agent_policies.py), `serialization` (agent_policy_compiler.py),
`create_claim` + `JobSigner` (job_service.py).

> `models/__init__.py:36-42` — F401 dar **INTENȚIONAT**: re-exporturi pentru înregistrarea
> modelelor SQLAlchemy. `UNKNOWN`/keep — nu se șterge (ar rupe `Base.metadata`).

### 3.2 S3 / Object Storage — feature jumătate-construit

| ID | Fișier:linie | Simbol | Clasificare | Dovadă | Risc | Acțiune |
|---|---|---|---|---|---|---|
| P6 | `object_storage.py:216` + `services/storage_service.py:189` | `ObjectStorage.presign_put` + ramura `PUT` din `StorageService.presign` | UNUSED_SYMBOL / SAFE_TO_DELETE | Singurul apel real (`routers/storage.py:141`) trimite mereu `method="GET"`; `presign_put` are 0 apelanți (doar fake în `conftest.py:179`) | Mic | Șterge metoda + ramura `else` |
| P7 | `services/storage_service.py:70-72` | `_build_key(..., version)` → segment `v{version}` | LEGACY | `version` e hardcodat `1` la ambele apeluri (`:109`, `:127`); nu crește niciodată | Mic | Elimină parametrul + segmentul, sau implementează versionarea reală |

Legat de ticketele existente **MIS-146** (presign_put mort) și **MIS-147** (scaffolding versionare).

### 3.3 Go agent — funcții inaccesibile (deadcode)

| ID | Fișier:linie | Simbol | Clasificare | Dovadă | Risc | Acțiune |
|---|---|---|---|---|---|---|
| G1 | `internal/agent/desired_policy.go:177` | `DesiredPolicyManager.TakeReport` | UNUSED_SYMBOL | deadcode unreachable; 0 apelanți prod/test | Mic | Șterge |
| G2 | `internal/agent/policy_sync.go:31` | `Manager.currentCollectorPolicies` | PROBABLY_DEAD | deadcode; doar în teste | Mic | Șterge (sau mută în test) |
| G3 | `internal/broker/operations.go:24` | `SetDeniedHook` | UNUSED_SYMBOL | deadcode; 0 apelanți prod/test | Mic | Șterge (hook de metrici neconectat) |
| G4 | `internal/communication/heartbeat_manager.go:26,31,45` | `HeartbeatManager` (ctor + `Run` + `beat`) | LEGACY — **NU ȘTERGE fără context** | deadcode; comentariu propriu: `ponytail: wired into AgentManager in Val 3; standalone for now.` | — | Păstrează; e deferral deliberat pentru Val 3 |
| G5 | `internal/compliance/collector.go:74` | `BuildRegistry` | PROBABLY_DEAD | deadcode unreachable; dar referit în comentarii (`manager.go:164`, `config.go:97`) | Mediu | Verifică dacă nu e apelat prin `Apply` hooks înainte |
| G6 | `internal/eq/queue.go:165` | `Queue.DroppedCount` | UNUSED_SYMBOL | deadcode; doar def + comentariu | Mic | Șterge sau expune în metrici |
| G7 | `internal/policy/canonical.go:14` | `CanonicalJSON` (pachet `policy`) | UNUSED_SYMBOL | deadcode; versiunea folosită e cea din `compliance/canonical.go` | Mic | Vezi D1 |
| G8 | `internal/policy/canonical.go:23` | `HashHex` | UNUSED_SYMBOL | deadcode; 0 apelanți | Mic | Șterge |
| G9 | `internal/security/envelope.go:124` | `MustCanonical` | LEGACY (test-only) | deadcode; comentariu: „for tests/fixed inputs"; 0 apelanți prod | Mic | Șterge dacă nu-l folosesc și testele (acum 1 ref de test) |
| G10 | `internal/security/envelope.go:140` | `NewVerifier` (v1 legacy) | PROBABLY_DEAD | deadcode; prod folosește `NewVerifierSet` (`job_validation.go:38`); doar teste îl cheamă | Mediu | Verifică compatibilitatea cu agenți vechi; probabil keep |

### 3.4 Go compliance

| ID | Fișier:linie | Simbol | Clasificare | Dovadă | Risc | Acțiune |
|---|---|---|---|---|---|---|
| GC1 | `internal/baseline/resolver.go:55` | `Resolver.Resolve` | UNUSED_SYMBOL | deadcode unreachable; comentariul propriu spune că `effectiveFor` a înlocuit vechiul „Resolve-per-agent loop (O(agents × full-table-scan))" | Mic | Șterge `Resolve` |

### 3.5 Frontend

| ID | Fișier | Simbol | Clasificare | Dovadă | Risc | Acțiune |
|---|---|---|---|---|---|---|
| F1 | `frontend/package.json` | `happy-dom` | **KEEP — false positive** | `vitest.config.ts` folosește `environment: 'nuxt'`; environment-ul din `@nuxt/test-utils/dist/vitest-environment.mjs:194` face `await import('happy-dom')` — peer dependency obligatorie | — | Nu elimina |
| F2 | `frontend/package.json` | `@vue/test-utils` | **KEEP — false positive** | `mountSuspended` (folosit în teste) trece prin `@nuxt/test-utils/dist/runtime/shared/vue-wrapper-plugin.mjs`, care importă `@vue/test-utils` — peer dependency obligatorie | — | Nu elimina |

**Rezolvat la implementare (2026-10-17):** F1 și F2 au fost verificate în `node_modules` înainte de
eliminare și **ambele sunt necesare** — `@nuxt/test-utils` le are ca peer dependencies opționale pe
harta lui, dar environment-ul `nuxt` le importă la runtime. Nicio dependență frontend nu se elimină.


**Fără componente orfane.** Scaneul pe nume a semnalat `TrendChart.vue` și `MetricsCards.vue`, dar
sunt folosite cu prefix de director (auto-import `pathPrefix:false`): `<ComplianceTrendChart>`,
`<VulnerabilityTrendChart>`, `<JobsTrendChart>`, `<ServerMetricsCards>`. **False positive — keep.**

### 3.6 Configurare moartă (Python Settings)

| ID | Fișier:linie | Câmp | Clasificare | Dovadă | Risc | Acțiune |
|---|---|---|---|---|---|---|
| C1 | `config.py:46` | `correlation_state_backend` | DEAD_CONFIGURATION | 0 referințe în tot repo (cod/compose/docs) | Mic | Șterge câmpul |
| C2 | `config.py:58` | `ca_signer_socket_path` | DEAD_CONFIGURATION | 0 referințe în tot repo | Mediu | Verifică dacă `ca-signer` nu-l citește prin alt nume |
| C3 | `config.py:84` | `job_signing_required` | DEAD_CONFIGURATION | Codul citește direct `os.environ["JOB_SIGNING_REQUIRED"]` (`job_envelope.py:79 signing_required()`), NU `settings.*` | Mediu | Aliniază: fie folosește settings, fie scoate câmpul |
| C4 | `config.py:104` | `s3_multipart_threshold_bytes` | DEAD_CONFIGURATION | 0 referințe în cod; doar în `docs/security/OBJECT_STORAGE.md:60` | Mic | Șterge (legat de P6/MIS-146) |

### 3.7 Variabile de mediu neutilizate (`.env.example`)

Chei fără nicio referință (case-insensitiv, excluzând `.env*`/docs/README):

```
AGENT_HEARTBEAT_INTERVAL   AGENT_HEARTBEAT_TIMEOUT   AGENT_MAX_OFFLINE_DAYS
AGENT_REGISTRATION_TOKEN_TTL   CERT_RENEWAL_DAYS
CVE_FEED_SOURCES   CVE_FEED_UPDATE_INTERVAL
PGBOUNCER_HOST   PGBOUNCER_PORT
PLUGINS_MAX_CPU_CORES   PLUGINS_MAX_MEMORY_MB   PLUGINS_SANDBOX_MODE
SLACK_ENABLED   SMTP_ENABLED   SMTP_FROM_ADDRESS   SMTP_USERNAME
TIMESCALE_DB   TIMESCALE_HOST   TIMESCALE_PORT   TIMESCALE_USER
```

Clasificare: `DEAD_CONFIGURATION` (probabil leftover/planificat).
**Atenție**: câteva (`PGBOUNCER_*`, `TIMESCALE_*`) pot fi folosite de tooling extern/manual — de
verificat înainte de eliminare. `POSTGRES_*`, `REDIS_*`, `NATS_*`, `PROMETHEUS_*` SUNT folosite
(compose + cod) → keep.

### 3.8 Scripturi și infrastructură

| ID | Fișier | Clasificare | Dovadă | Acțiune |
|---|---|---|---|---|
| S1 | `scripts/load_events.py` | PROBABLY_DEAD | 0 referințe în repo | Confirmă (tool manual de test?) apoi șterge |
| S2 | `scripts/recover-rocky-agent.sh` | PROBABLY_DEAD | 0 referințe în repo | Confirmă apoi șterge |

Restul scripturilor (`check-versions.sh`, `docker-init.sh`, `init-certificates.sh`, `install-agent.sh`,
`loki-cli.sh`, `release-platform.sh`, `scripts/security/*.sh`) sunt referite din Makefile/docs/skills → keep.
Dockerfile-urile și `security-pipeline.yml` sunt active → keep.

### 3.9 Duplicare

| ID | Subiect | Clasificare | Detaliu | Recomandare |
|---|---|---|---|---|
| D1 | Canonical JSON în agent | DUPLICATE | Două implementări: `internal/compliance/canonical.go:46` (`CanonicalJSON(facts Facts)`) și `internal/policy/canonical.go:14` (`CanonicalJSON(v interface{})`); plus `security.MustCanonical` | Posibil intenționat (payload-uri diferite) — verifică dacă pot fi unificate sub o singură funcție generică |
| D2 | `stores/workflow.ts` vs `stores/workflows.ts` (frontend) | NOT duplicate | `workflow.ts` = editor/graf de execuție; `workflows.ts` = listă CRUD. Ambele folosite | Keep |
| D3 | `services/agent_policies.py` vs `services/agent_policy_compiler.py` | NOT duplicate | Roluri diferite (CRUD vs compilare spec) | Keep (dar vezi P1/P2) |

## 4. Artefacte temporare / pe disc (nu sunt în git)

| ID | Path | Mărime | Status git | Recomandare |
|---|---|---|---|---|
| A1 | `.claude/worktrees/{analiza-implementarii-44c8f7, app-analysis-progress-0c17c7, linear-functionality-b9462c}` | **565 MB** | ignorat | `git worktree remove` cele 3 (branch-uri `claude/*`); nu afectează repo |
| A2 | `.aislop/worktrees/agent-20260718-122541-1754934` | — | ignorat | Worktree detached stale — `git worktree prune` + remove |
| A3 | `graphify-out/` (11 MB), `sbom/` (1.6 MB), `banks/`, `.planning/`, `.gstack/` | — | ignorate | Generate — curățabile oricând, nu intră în commit |
| A4 | `logs/` | 0 | untracked | Gol; ignoră (nu e în `.gitignore` dar nici tracked) |

Nu există fișiere backup/temp tracked (`.bak`, `.orig`, `.old`, `~`, `.DS_Store`, `copy.*`) — verificat.

## 5. Necunoscute / acoperire parțială (`UNKNOWN`)

Următoarele zone NU au fost epuizate în acest audit și **nu se ating** fără o a doua trecere dedicată:

- **Dead API endpoints**: mapping complet frontend↔backend (apeluri `useApi()` vs rute FastAPI) — neefectuat.
- **Dead DB artifacts**: modele/câmpuri/tabele/enum/migrations fără consumator — neefectuat.
- **TS exports neutilizate** dincolo de componente (knip nu e instalat; nu există config).
- **staticcheck** (Go) — neinstalat pentru versiunile de toolchain; `go vet` + `deadcode` au rulat.
- **Duplicate logic** dincolo de D1 — scan parțial.

## 6. Riscuri & impact

- **Impact global**: mic. Toate elementele confirmate sunt cod fără consumatori; comportamentul
  aplicației nu se schimbă prin eliminare.
- **Riscuri punctuale**:
  - C3 `job_signing_required` — NU șterge orbește: atinge calea de securitate a joburilor. Aliniază
    întâi (`settings` vs `os.environ`) și rulează `.claude/skills/ship-changes` pe backend.
  - G4 `HeartbeatManager` — deferral deliberat (Val 3). **Keep.**
  - G10 `security.NewVerifier` / G5 `compliance.BuildRegistry` — pot fi păstrate pentru
    compatibilitate/reflection. Necesită confirmare înainte de ștergere.
  - P3 `BaselineApprovalResponse` — poate fi consumat de clienți API externi.

## 7. Dovezi / verificări rulate

```
ruff 0.15.20        F401,F811,F841,F822,F823  → 15 findings (7 re-exporturi intenționate)
vulture 2.16        --min-confidence 60       → 753 hinturi (zgomotos pe FastAPI; folosit ca indiciu)
deadcode@v0.30.0    agent                     → 12 funcții unreachable
deadcode@v0.35.0    compliance                → 1 funcție unreachable (Resolver.Resolve)
go vet ./...        agent (go1.24)            → clean (exit 0)
go vet ./...        compliance (go1.25)       → clean (exit 0)
manual cross-ref    pentru fiecare candidat   → vezi coloana „Dovadă" din §3
```

Comenzi reproduce în anexă la cerere (rulări în containere `golang:1.24`/`golang:1.25`, read-only).

## 8. Cleanup executat (2026-10-17)

Fiecare etapă = commit separat, cu verificări înainte de commit. Ordine de la risc mic la mare.

| Etapă | Ce | Commit | Verificare | Stare |
|---|---|---|---|---|
| 1 | Importuri neutilizate (P4) — 8 importuri | `3ade3d1` | ruff F curat, pytest 782 passed | ✅ |
| 2 | `PolicyOut`, `VersionOut`, condiția `or True` (P1, P2, P5) | `adcc657` | pytest 782 passed | ✅ |
| 3 | S3 scaffolding: `presign_put`, ramura PUT, parametrul `version` (P6, P7) | `9d07166` | pytest 782 passed | ✅ |
| 4 | Config moartă: C1, C2, C3, C4 | `ff25075` | pytest 782 passed, ruff F curat | ✅ |
| 5 | Go agent: G1, G3, G7, G8, G5 (deadcode) | `6639026` | go vet curat, `go test ./... -race` verde, deadcode 12→7 | ✅ |
| 5b | Go compliance: `Resolver.Resolve` (GC1) | `81954a5` | go vet curat, `go test ./... -race` verde, deadcode 1→0 | ✅ |
| 6 | Dependențe frontend (F1, F2) | — | **verificate în `node_modules` → false positive, KEEP** | ⛔ fără acțiune |
| 7 | Scripturi orfane (S1, S2) | — | în așteptare de confirmare umană | ⏸ |
| 8 | Worktree-uri stale (A1, A2) | — | în așteptare (operație pe disc, nu pe repo) | ⏸ |
| 9 | Env leftover (§3.7) | — | în așteptare de confirmare per cheie | ⏸ |

**Păstrate intenționat** (deadcode le raportează, dar au consumator real):
`communication/heartbeat_manager.go` (deferral `ponytail: Val 3`),
`eq.Queue.DroppedCount` (singurul semnal de overflow),
`policy_sync.go currentCollectorPolicies` (accesor de test),
`security.MustCanonical` / `security.NewVerifier` (folosite de teste),
`internal/compliance/collector.go NewFileIntegrityCollectorWithConfig` (încă folosit).

### Baseline de teste

`pytest` (backend): **782 passed, 3 failed**. Cele 3 eșecuri sunt **preexistente** la HEAD
(`tests/security/test_security_p0.py` — fake-ul de settings nu are `agent_cert_ttl_days`),
verificate identic înainte și după fiecare commit. Nu au fost introduse de cleanup.

`go test ./... -race`: agent și compliance — integral verde.

## 9. Metrici (finale, după cleanup)

| Metrică | Audit | După cleanup |
|---|---|---|
| Fișiere tracked analizate | 846 | 846 |
| Simboluri/importuri neutilizate identificate | ~23 | **0 rămase neadresate** (restul păstrate justificat) |
| Fișiere tracked candidate pentru eliminare | 0 | 0 |
| Dependențe candidate pentru eliminare | 2 | **0** (F1/F2 = false positive) |
| Câmpuri de config moarte | 4 | **0** |
| Funcții Go inaccesibile (deadcode) | 13 | **7** (toate păstrate cu motiv) |
| Duplicări identificate | 1 | 1 (neprodusă — necesită decizie de compatibilitate) |
| Linii de cod eliminate | — | ~150 (net, 9 commits) |

## 10. Commituri

```
05360be docs(audit): add dead code audit report
3ade3d1 refactor(backend): remove unused imports flagged by ruff F401
adcc657 refactor(policies): drop dead PolicyOut/VersionOut and dead if-condition
9d07166 refactor(storage): remove dead presign_put path and version scaffolding
ff25075 refactor(config): remove 4 unused Settings fields
6639026 refactor(agent): remove dead code reported by deadcode
81954a5 refactor(compliance): remove unused Resolver.Resolve
```

## 11. Rămas de făcut (nu acționat, necesită decizie)

- **S1/S2** (`scripts/load_events.py`, `scripts/recover-rocky-agent.sh`) — confirmă dacă sunt
  tool-uri manuale în afara repo-ului.
- **A1/A2** — `git worktree remove` pentru cele 3 worktree-uri din `.claude/worktrees` (565 MB)
  + `git worktree prune` pentru `.aislop`. Operație pe disc, nu atinge codul.
- **§3.7** — cele 20 de chei `.env.example` fără referință, una cu una.
- **D1** — Canonical JSON: policy / compliance / security — decide dacă se unifică.
- **MIS-159** — audit continuare: dead endpoints, artefacte DB, exporturi TS, `staticcheck`.
- **P3** `BaselineApprovalResponse` — confirmă lipsa consumatorilor externi.
- **Teste preexistente broken** (`test_security_p0.py`, `agent_cert_ttl_days`) — raportat, neatins.
