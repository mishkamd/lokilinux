# 09 — Recomandări: remediere & dezvoltare

> Document de recomandări, august 2026, bazat pe analiza codului la commit `77c4220` (v0.3.0). Fiecare recomandare are dovezi în cod (`fișier:linie`), impact evaluat și efort orientativ (S < 1 zi, M 1–3 zile, L > 3 zile).

## Metodologie

Recomandările provin din trei surse: analiza directă a codului (gap-uri între config/cod, cod mort, debt declarat în comentarii), `PRODUCT.md` (backlog confirmat de produs) și design-urile deja scrise (`08-api-public-mcp.md`). Nimic ghicit — fiecare rând poate fi verificat.

## A. Remedieri prioritare

### R1 — Paralelism job-uri necontrolat pe agent · prioritate HIGH · efort S

**Problema:** `job_execution.max_parallel_jobs` există în config cu default 2 (`agent/internal/config/config.go:46,96-98`) dar **nu e referențiat nicăieri** în `manager.go` sau module — agentul pornește oricâte job-uri primesc într-un heartbeat, fără limită. Singurul guard e `inFlight`, care împiedică doar dublul *aceluiași* job.

**Impact:** un val de policy/workflow jobs pe un agent mic (2 vCPU) poate satura hostul; playbook-uri Ansible paralele se calcă în picioare pe lock-uri de package manager.

**Remediere:** semafor contorizat (`chan struct{}` capacitate `MaxParallelJobs`) achiziționat în goroutine-ul de dispatch din `handleResponse`; jobs peste limită rămân la server până la următorul heartbeat (serverul nu redispatch ce e PENDING/RUNNING — comportamentul actual se păstrează).

### R2 — `sandbox_enabled` configurabil dar inexistent · prioritate LOW · efort S (eliminare) / L (implementare)

**Problema:** `agent/internal/config/config.go:48` definește `sandbox_enabled` — zero utilizări în cod.

**Impact:** promite o funcție care nu există; operatorii pot crede că job-urile rulează sandbox-uite. În realitate sandbox-ul agentului e cel systemd (ProtectSystem), iar playbook-urile ies deliberat din el prin systemd-run.

**Remediere:** fie ștergem cheia + intrarea din documentație (S), fie implementăm sandbox real per-job prin proprietăți systemd-run suplimentare (L). Recomand eliminarea până când există cerință concretă.

### R3 — Subiecte NATS moarte pentru rezultate compliance · prioritate MEDIUM · efort S–M

**Problema:** `lokilinux.compliance.drift.detected` și `.score.updated` sunt definite în `backend/lokilinux/nats_topics.py:35-36`, dar **niciun producător, niciun consumator** — serviciul Go nu publică nimic pe NATS (`ingest.go` nu are client NATS); backendul nu le subscrie. Rezultatele circulă exclusiv prin tabelele Postgres partajate.

**Impact:** frontendul face polling pentru schimbări de drift/scor; invalidarea cache-ului Redis al API-ului nu se întâmplă event-driven — latență inutilă și query-uri repetate.

**Remediere:** varianta minimă (M): Ingester primește un publisher NATS opțional și publică evenimentele la insert/incident nou; API câștigă un worker care invalidează cache-ul dashboard/compliance. Varianta completă (L): push live spre UI prin SSE/WebSocket — vezi N3.

### R4 — CVE doar pe dnf/yum; Debian/Ubuntu orbe la vulnerabilități · prioritate **CRITICAL** · efort L

**Problema:** cross-referencing-ul pachet→CVE e implementat doar pentru dnf/yum în `agent/internal/modules/package_manager.go`. Pe apt/dpkg listarea pachetelor merge, dar scanarea vulnerabilităților nu are sursă legată. Confirmat ca backlog real în `PRODUCT.md` („Closing this gap … is a real backlog item").

**Impact:** platforma se poziționează cross-distro (RHEL/Rocky/Oracle/Debian/Ubuntu), dar pe jumătatea Debian/Ubuntu feature-ul principal — vulnerability tracking — tace. Fals sentiment de acoperire în dashboard.

**Remediere:** integrare feed OVAL/DSA pentru Debian+Ubuntu (sau USN API) procesată de CVEEnrichmentWorker; mapare dpkg→CVE în agent sau server-side. Decizie de arhitectură: scanare pe agent (ca azi) vs centralizată pe control plane (feed-uri mai ușor de updatat fără redistribuire binar). Recomand centralizat — agentul trimite inventar, serverul potrivește CVE.

### R5 — Fără negociere capabilități agent-server · prioritate MEDIUM · efort M

**Problema:** pașii workflow nativi ai agentului (SERVICE/FILE/SYSTEM/PACKAGE + WORKFLOW_STEPS) sunt scriși și testați, dar backendul îi compilează defensiv la shell `CUSTOM_COMMAND` tocmai pentru că protocolul (`proto/lokilinux.proto`) nu transportă versiunea/capabilitățile agentului (`manager.go:405-421` — comentariu explicit).

**Impact:** capabilități native moarte; shell fallback pierde semantică (ex. validări, exit codes specifice) și auditabilitate fină.

**Remediere:** adaugă `agent_version` + `capabilities[]` în `AgentHeartbeatRequest` (câmpurile 12-19 sunt deja rezervate în proto!); backendul ține capabilități per agent și activează dispatch nativ doar unde există suport. Depinde parțial de R6 (bucla tipizată face schimbul natural).

### R6 — Bucla heartbeat tipizată scrisă, neconectată · prioritate LOW · efort S

**Problema:** `communication/heartbeat_manager.go` implementează bucla pe mesajele proto generate; comentariul spune „wired into AgentManager in Val 3". Managerul activ folosește în continuare harta liberă `map[string]interface{}`.

**Impact:** debt declarat; două implementații ale aceleiași bucle = risc de divergență la fiecare modificare de protocol.

**Remediere:** fie conectare efectivă (+ R5 devine trivial), fie ștergerea fișierului cu mențiunea în istoric. Recomand conectarea — pregătește terenul pentru proto binar real.

## B. Implementări noi recomandate

| ID | Ce | De ce acum | Ref |
|----|-----|-----------|-----|
| N1 | **PAT/API tokens** cu scopes + rate limit | fundament pentru orice consum extern; design complet gata | `docs/modules/08-api-public-mcp.md` |
| N2 | **Server MCP** (fastmcp, 7 tools read-only întâi) | ops invocabile din AI; moștenește auth/RBAC/audit prin REST | idem |
| N3 | **Push live compliance** (SSE/WebSocket) folosind subiectele din R3 | drift vizibil în secunde, nu la următorul poll; UX conform principiului „onest despre latență" | R3 |
| N4 | **Scoring ponderat + mapping framework-uri** (CIS benchmark, ISO 27001) | azi `scoring.Classify(domain)` e o clasificare simplă; enterprise cere raport pe framework-uri | `scoring.go:36`, `framework_mapping.py` |
| N5 | **Reguli de suppressie drift** (pattern-based, cu expiry + audit) | azi suppress e manual per event — noise-ul recurent (ex. mount temporar) trebuie tăiat sistematic | `routers/compliance/drift.py` |
| N6 | **Modul Go comun pt. hashing** (agent ↔ serviciu) | duplicația `canonicalHash` e documentată ca intenționată până la al 3-lea consumator — MCP/scoring extern ar fi al treilea | `ingest.go:70-75` |

## C. Matrice prioritizare

```
                 Efort mic ────────────────► Efort mare
Impact mare   │ R1 paralelism        │ R4 CVE multi-distro │
              │ R3 subiecte NATS     │                     │
──────────────┼──────────────────────┼─────────────────────┤
Impact mediu  │ R6 bucla tipizată    │ R5 capability neg.  │
              │ N1 PAT               │ N2 MCP, N3 push     │
──────────────┼──────────────────────┼─────────────────────┤
Impact mic    │ R2 sandbox cleanup   │ N4 scoring,         │
              │                      │ N5 suppression      │
```

## Ordinea recomandată

> **Actualizare:** stările fantomă `IN_REMEDIATION`/`EXCEPTION` ale incidentelor de drift (identificate la analiza incidents) primesc acum un design complet de conectare în [`10-compliance-autopilot.md`](10-compliance-autopilot.md) — secțiunea A3.

1. **R1** — bug de resource control, fix într-o zi, risc imediat pe fleet-uri aglomerate.
2. **N1** — deblochează N2, N3 și orice integrare viitoare.
3. **R4** — cea mai dureroasă gaură de produs; necesită decizie de arhitectură (scanare agent vs centralizată) — o săptămână de spike, apoi implementare.
4. **R3 + N3** — transformă rezultatele compliance în timp-real aproape.
5. **R6 → R5** — lanțul capability negotiation, deblochează executorii nativi.
6. Restul după nevoie: N2, N4, N5, R2, N6.
