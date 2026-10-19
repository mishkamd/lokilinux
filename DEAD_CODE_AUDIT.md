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
| F1 | `frontend/package.json` | `happy-dom` | UNUSED_DEPENDENCY | `vitest.config.ts` folosește `environment: 'nuxt'` (`@nuxt/test-utils/config`); `happy-dom` apare doar în README | Mic | Scoate din `dependencies` (dacă nu-l cere alt setup) |
| F2 | `frontend/package.json` | `@vue/test-utils` | PROBABLY_DEAD | Testele importă `@nuxt/test-utils/runtime`; `@vue/test-utils` e dep tranzitivă a `@nuxt/test-utils` | Mediu | Verifică peer-deps; posibil declarat direct intenționat |

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

## 8. Plan de cleanup în etape (după aprobare)

Fiecare etapă = commit separat + verificări §6 din task. Ordine de la risc mic la mare.

1. **Importuri neutilizate (P4)** — `ruff --fix` controlat + review diff. Verificare: `ruff check`,
   `mypy --strict`, `pytest`.
2. **Simboluri Python moarte (P1, P2, P5)** — șterge `PolicyOut`, `VersionOut`, curăță `or True`.
   Verificare: `pytest`.
3. **S3 scaffolding (P6, P7, C4)** — șterge `presign_put` + ramura PUT + parametrul `version` +
   câmpul `s3_multipart_threshold_bytes`. Verificare: `pytest tests/...test_storage*`.
4. **Config moartă (C1, C2)** — șterge `correlation_state_backend`, `ca_signer_socket_path` (după
   confirmare ca-signer). C3 tratat separat (securitate).
5. **Go dead code (G1, G2, G3, G6, G7, G8, G9, GC1)** — șterge doar ce nu e LEGACY/compat.
   Verificare: `go test ./... -race` (agent + compliance), `go vet`.
6. **Dependențe frontend (F1, F2)** — scoate `happy-dom`; confirmă `@vue/test-utils`.
   Verificare: `npm test`, `npx vue-tsc --noEmit`, `npm run build`.
7. **Scripturi orfane (S1, S2)** — după confirmare. Verificare: build imagini.
8. **Artefacte pe disc (A1, A2)** — `git worktree remove`/`prune` (nu atinge repo). Fără commit.
9. **Env leftover (§3.7)** — curață `.env.example` după confirmarea fiecărei chei.

Recomandare: etapele 1–4 într-o singură sesiune (backend), 5 (Go), 6 (frontend) separat, apoi 7–9.

## 9. Metrici

| Metrică | Valoare |
|---|---|
| Fișiere tracked analizate | **846** (+ directoare ignorate relevante) |
| Simboluri/importuri neutilizate identificate | **~23** (P1–P7, G1–G10, GC1) |
| Fișiere tracked candidate pentru eliminare | **0** (niciunul nu e fișier întreg; S1–S2 = 2 scripturi de confirmat) |
| Dependențe candidate pentru eliminare | **2** (F1 sigur, F2 de confirmat) |
| Câmpuri de config moarte | **4** (C1–C4) + **20** chei env de verificat |
| Duplicări identificate | **1** confirmată (D1) + 2 verificate ca NON-duplicate |
| Probleme confirmate | ruff F401 (8 reale), deadcode (13), go vet curat, P5–P7, C1–C4, F1 |
| Elemente încă incerte | P3, G5, G9, G10, F2, §3.7, §5 (endpoints/migrations/knip) |

## 10. Ce necesită aprobare explicită

- [ ] Etapa 1 (importuri) — 8 ștergeri de import.
- [ ] Etapa 2 (P1, P2, P5).
- [ ] Etapa 3 (P6, P7, C4) — atinge storage.
- [ ] Etapa 4 (C1, C2) — după confirmare; C3 (securitate) rămâne în afara acestui cleanup.
- [ ] Etapa 5 (Go) — doar G1, G2, G3, G6, G7, G8, G9, GC1; G4/G5/G10 excluse.
- [ ] Etapa 6 (F1, F2) — frontend deps.
- [ ] Etapele 7–8 (scripturi + worktrees).
