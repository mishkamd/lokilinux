# 04 — Microserviciu Compliance (Go)

> Documentație generată din cod la commit `77c4220`, august 2026. Detalii suplimentare: `docs/compliance/00-OVERVIEW.md` … `13-OPS.md`.

## Rol

`lokilinux-compliance` este calea fierbinte (hot path) CPU-bound a modulului Infrastructure Compliance & Drift Management: ingest snapshot-uri de la agenți, detecție drift, evaluare reguli CEL, scoring și programarea assessment-urilor. **Nu expune REST public** — doar `/healthz` (:8080) și Prometheus `/metrics` (:9091). Consumă NATS JetStream, citește/scrie direct în Postgres.

Motivația arhitecturală: ingest + diff + evaluare pe mii de agenți sunt operații CPU-intensive — separate de FastAPI, care păstrează doar CRUD-ul user-facing (autentificare, audit, job engine moștenite).

## Tehnologii

| Componentă | Valoare |
|---|---|
| Go | 1.25 |
| pgx / pgxpool | Acces direct Postgres |
| NATS JetStream | Consum snapshot-uri + leader election prin KV |
| CEL (cel-go) | Limbajul expresiilor pentru evaluarea regulilor |
| **BLAKE3** | Hash canonizat facts (identic cu agentul) + chei de correlație drift |
| Fiber | Server healthz |
| Prometheus client | Metrice |
| Distroless | Imagine finală fără shell (healthcheck self-probe) |

## Compoziție

```
services/compliance/
├── cmd/compliance/main.go     # Entry-point (257 linii): wiring complet
└── internal/
    ├── config/                # YAML + env (/etc/lokilinux/compliance.yaml)
    ├── ingest/                # Ingest snapshot-uri: consumer JetStream → Ingester
    │   ├── consumer.go        #   Start(ctx, stream, durable, maxAckPending); Term vs Nak
    │   ├── ingest.go          #   Pipeline-ul complet per snapshot (615 linii — nucleul serviciului)
    │   └── file_integrity.go  #   Breakdown-ul per-fișier al domeniului file_integrity
    ├── baseline/              # Resolver baseline_effective per agent
    │   ├── resolver.go        #   Resolve / RecomputeAll / ReconcileOnStartup; deep-merge selectors
    │   └── consumer.go        #   Subscr. COMPLIANCE_BASELINE_PUBLISHED → invalidare flota
    ├── drift/                 # detector.go: Detect(domain, comparedAgainst, old, new) → Event + FieldDiff
    ├── rules/                 # engine.go: evaluator CEL — Rule/Verdict/Evidence/platform
    ├── policy/                # resolver.go: MatchingSetIDs(attrs, assignments) — ce policy sets se aplică
    ├── scoring/               # Classify(domain) → categorie de scor
    ├── scheduler/             # Leader election + dispatch
    │   ├── leader.go          #   Lease TTL pe NATS KV bucket
    │   ├── kv_adapter.go      #   Adaptor jetstream.KeyValue → KVStore
    │   ├── dispatch.go        #   Dispatcher: Job.scheduled_time scadent → dispatch
    │   ├── assessment.go      #   AssessmentPoller: claim + rulează assessment-uri pending (5s)
    │   └── exceptions.go      #   Expirer: excepții ACTIVE cu expires_at trecut → EXPIRED (60s)
    ├── scope/                 # selector.go: Matches(selector, attrs); PlatformID(distro, version)
    ├── storage/
    │   └── postgres.go        # Toate interogările SQL (~960 linii) + Transact() pentru scrieri atomice
```

## Pipeline-ul de ingest (`ingest/ingest.go`)

Pentru fiecare mesaj `lokilinux.compliance.snapshot.{domain}`:

0. **Atomicitate** — pașii 2-7 rulează într-o singură tranzacție Postgres (`storage.Transact`). Orice eșuc dă rollback complet, deci un redelivery JetStream reîncepe de la o tablă curată. Replay-ul unui snapshot identic (unchanged) **sare** peste scrierile blob/snapshot — re-inserarea le-ar duplica și ar umfla `ref_count` la fiecare retry.
1. **Verificare hash** — recalculează BLAKE3 peste facts exact ca agentul (`canonicalHash`, duplicat deliberat între modulele Go separate) și respinge mismatch-ul. Snapshot neverificat ar otrăvi drift/scoring pentru acel agent+domeniu.
2. **Drift vs snapshot anterior** — dacă există hash precedent și diferă: `drift.Detect(...)` produce un Event cu FieldDiff per cale de câmp.
3. **Stocare content-addressable** (doar dacă statele diferă) — blob-ul facts intră în `inventory_blobs` (upsert după hash — deduplicare naturală), apoi rând nou în `inventory_snapshots`.
4. **Drift vs baseline efectiv** — comparare *independentă* de pasul 2: o abatere de la baseline e raportabilă chiar la primul snapshot al unui agent.
5. **Evaluare reguli** — vezi secțiunea dedicată mai jos.
6. **Scoring** — dacă s-au evaluat reguli, recompute scoruri pentru agent.
7. **Caz special `file_integrity`** — pe lângă calea generică (care îi dă oricum blob + drift event la nivel de domeniu): breakdown per fișier în tabelele `file_hashes`/`file_changes` (migrarea 017), cu pattern-uri de ignore din DB, tratare `DELETED` și **reevaluarea incrementară** a exact regulilor care depind de căile modificate (correlation, nu mai așteaptă următorul snapshot programat).

### Erori permanente vs tranzitorii

Erorile care nu se pot vindeca la retry (JSON malformat, `agent_id` invalid, **hash mismatch**) sunt marcate `permanentError` iar consumerul le face **Term** (acknowledge + terminare), nu Nak. Motiv documentat în cod: aceeași clasă de eroare (structuri nested hash-uite diferit server-side, fixată ulterior prin `Normalize` în agent) a ținut un core CPU ocupat 4 zile pe ~30k mesaje care nu puteau niciodată reuși.

## Detecția drift și deduplicarea ei

- Două baze de comparație (`drift.ComparedAgainst`): `previous_snapshot` și `baseline`.
- Severitate clasificată per domeniu (`ClassifySeverity`).
- **Deduplicare prin correlation key**: BLAKE3(domain ∥ comparedAgainst ∥ căi de câmp sortate). La fiecare poll cu aceeași abatere → `IncrementDriftOccurrence` pe incidentul deschis existent; doar o abatere *nouă* inserează rând. Rezultat: **un incident deschis cu contor de apariții**, niciodată un rând per ciclu de heartbeat.

## Evaluarea regulilor (CEL)

`evaluateRules(ctx, snap)` (`ingest.go:329`):

1. Load atribute agent (distro, versiune etc.) din DB.
2. `policy.MatchingSetIDs(attrs, assignments)` — assignment-urile globale se potrivesc mereu; cele scoped filtrează pe atribute (`scope.Matches`).
3. Fără policy sets potrivite → nimic de evaluat (ieșire timpurie).
4. Reguli active pentru seturile + domeniul respectiv → per regulă:
   - aplicabilitate de platformă: `scope.PlatformID(os_distro, os_version)` (ex. `ubuntu-22.04`);
   - verdict CEL pe facts (variabila `facts` expusă expresiei), cu valori actuale extrase pe căi punctate;
   - evidence structurat + `evidenceHash`;
   - tag-uire cu excepțiile active ale regulii;
   - un rând `rule_evaluations` per verdict.

## Rezoluția baseline-urilor (`baseline/resolver.go`)

`Resolve(agentID)` → `Effective`: pornește din published baselines (doar versiuni `PUBLISHED` ale baseline-urilor enabled, `LoadPublishedBaselines`), potrivește `scope_selector` pe atributele agentului și face **deep merge cu overwrite** (`deepMergeOverwrite`) în ordinea aplicării. Starea fuzionată se persistă în `baseline_effective` cu hash canonizat.

- `RecomputeAll` — recalcul pentru toți agenții;
- `ReconcileOnStartup` — completează doar agenții fără rând (gardă contra pierderii backlog-ului NATS);
- `BaselineConsumer` — la `COMPLIANCE_BASELINE_PUBLISHED` declanșează invalidare fleet-wide.

## Scheduler-ul

Leader election pe NATS KV (lease TTL, `node_id` = hostname) — o singură instanță activă:

| Componentă | Tick | Rol |
|---|---|---|
| `Dispatcher` | 10s | Job-uri compliance cu `scheduled_time` scadent → dispatch |
| `Expirer` | 60s | Expiră excepții ACTIVE cu `expires_at` trecut |
| `AssessmentPoller` | 5s | Claim + rulează assessment-uri cerute din API |

## Wiring la startup (`main.go`) și oprire

1. Config → NATS (fatal dacă lipsește) → Postgres (DSN keyword=value, nu URI — parolele generate conțin caractere care strică parsarea URI; comentariu în compose documentează hang-ul real).
2. Evaluator CEL → Ingester → `EnsureStream` JetStream → IngestConsumer + BaselineConsumer (durables distincte pe același stream).
3. Reconciliere baseline la startup.
4. Leader elector + Dispatcher + Expirer + AssessmentPoller.
5. healthz (:8080, net/http; degradează cu 503 când NATS e deconectat) + metrics (:9091, promhttp). La SIGTERM/SIGINT: se oprește fetch-ul JetStream și se **drenează** handlerii în zbor (`consumeCtx.Drain()` + așteptare limitată la 6s) înainte de shutdown-ul serverelor HTTP — un deploy nu mai trunchiază pipeline-uri la jumătatea scrierii.

## Interacțiunea cu restul sistemului

- **CRUD user-facing** stă integral în FastAPI (`routers/compliance/*`). Serviciul Go nu vede HTTP deloc.
- **Schimbul de rezultate e prin tabelele Postgres partajate** — API-ul citește direct `drift_events`, `rule_evaluations`, `file_changes`, scorurile compute aici. Nu există callback NATS spre backend.
- ✅ Subiectele `lokilinux.compliance.drift.detected` și `.score.updated` au fost **șterse din `nats_topics.py`** (nu au avut niciodată producător/consumator); dacă se dorește push WebSocket/cache invalidare, se re-adaugă odată cu producătorul din serviciul Go. Idem `hashes.reported` — publicarea per-heartbeat fără consumator a fost eliminată din gRPC passthrough.
- Singurele subiecte active: `compliance.snapshot.{domain}` (producător: servicer gRPC) și `compliance.baseline.published` (producător: API; consumator: BaselineConsumer).
- **Job-uri remediere** pornesc prin backend (worker + heartbeat), nu direct de aici.

## Dependențe

Postgres (pgBouncer), NATS JetStream (+KV leadership). Fără Redis. Certificat CA montat read-only.

## Decizii de design

1. **Hibrid Go/FastAPI** — CPU-bound în Go, CRUD în FastAPI (auth/audit gratuite). `docs/compliance/02-GO-SERVICE.md`.
2. **Fără REST propriu** — suprafață minimă; tot traficul utilizator prin API-ul existent.
3. **BLAKE3 content-addressable** — blobs deduplicate după hash, verificare end-to-end agent→serviciu, chei de correlație drift deterministe.
4. **Term pentru erori permanente** — retry fără sens trebuie terminat, nu reluat la infinit (lecția celor 30k mesaje / 4 zile CPU).
5. **Leader election pe NATS KV** — fără etcd/consul; reconcilierea la startup acoperă evenimentele pierdute.
6. **Un incident deschis per abatere unică** — correlation key cu BLAKE3; contor de apariții în loc de spam de evenimente.

## Autopilot (planificat)

Colectarea, drift-ul și evaluarea sunt automate azi; management-ul (baselines, assessments, remediere) rămâne manual. Design-ul complet de simplificare+automatizare — baseline adopt într-un singur apel, assessment programat global, auto-remediere gated pe allowlist, conectarea stărilor `IN_REMEDIATION`/`EXCEPTION` — e specificat în [`10-compliance-autopilot.md`](10-compliance-autopilot.md).
