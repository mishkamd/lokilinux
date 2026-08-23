# 10 — Compliance Autopilot (design detaliat)

> Document de design, august 2026. Starea actuală reflectă codul la commit `77c4220`. Tot ce urmează e **specificație de implementare**, nu cod existent — fiecare secțiune indică exact ce se adaugă, unde, cu ce reguli și ce criterii de acceptanță are.

## Scop

Modulul compliance colectează, detectează drift și evaluează reguli **automat** (prin heartbeat), dar ciclurile de management sunt manuale și verbose:

| Flux azi | Pași manuali | După Autopilot |
|---|---|---|
| Baseline | create → submit → approve → publish (4 apeluri) | **1 apel** (`adopt`) sau automat |
| Assessment | POST manual, fără programare | programat global, la interval |
| Remediere | DRAFT → submit → approve → execute | opțional complet automat, gated pe allowlist |
| Stări incident | `IN_REMEDIATION`/`EXCEPTION` moarte | conectate la fluxurile reale |

## Principii de design

1. **Opt-in explicit pentru acțiuni pe host** — citirea/evaluarea pot fi implicite; *scrierea* pe hosturi (remediere) pornește oprit și se activează doar cu allowlist.
2. **Reutilizare peste invenție** — Autopilotul folosește workerii existenți (AssessmentPoller Go, RemediationSchedulerWorker, RemediationVerificationWorker); singurele piese noi sunt declanșatoarele programate și punctele de decizie.
3. **Audit integral** — orice acțiune automată poartă actor `system:<mechanism>` în `audit_log`; nimic silențios.
4. **Onestitate** — dashboardul etichetează clar ce vine din automat vs manual (câmp `trigger_type` deja existent pe planuri).
5. **Kill-switch unic** — fiecare automatizare se oprește printr-o singură cheie de settings, fără redeploy.

---

## S1 — Baseline Adopt (4 pași → 1)

### Problema

Fără baseline publicat, comparația „vs baseline" din pipeline-ul Go tace silențios pentru agentul respectiv (`detectBaselineDrift` iese când `GetBaselineEffective` nu găsește rând). Crearea manuală cere 4 apeluri versionate. Rezultat: majoritatea flotelor rulează fără protecția de baseline pentru că costul de start e prea mare.

### API nou

```
POST /api/v1/compliance/baselines/adopt
Role: MANAGER sau ADMIN
Body:
{
  "scope_type": "GLOBAL" | "OS" | "ROLE" | "ENVIRONMENT" | "DATACENTER" | "CLUSTER" | "APPLICATION",
  "scope_selector": {},              // ex. {"os_distro": "ubuntu"}; {} = global
  "domains": ["sshd", "sysctl"],     // opțional; lipsă = toate domeniile cu snapshot existent
  "sample_agent_ids": [],            // opțional: agenți din care se extrage starea;
                                     //   lipsă = primii N agenți care se potrivesc scope-ului
  "name": null,                      // opțional; default "Adopted <scope> <data>"
  "auto_publish": true               // false = se oprește la PENDING_APPROVAL
}
```

### Flux

```
1. Rezolvă agenții din scope (aceeași logică ca assessments: scope.Matches pe atribute).
2. Per domeniu cerut:
   a. ultimul snapshot per agent din inventory_snapshots + inventory_blobs
      (interogare identică cu cea din detectBaselineDrift, partajată prin storage);
   b. fuzionează facts-urile sample-ului: câmpuri identice peste tot sample-ul → valoare;
      câmpuri divergente → valoare + listă variantelor (transparență);
      domeniu fără niciun snapshot → skip cu motiv în răspuns;
   c. expected_state = rezultatul fuziunii (JSONB).
3. create_version(content_hash=_content_hash(expected_state)) — reutilizează
   BaselineService existent (baseline_service.py:85), inclusiv dedup-ul pe hash:
   adopt repetat fără schimbări NU creează versiuni noi.
4. submit(actor) → approve(actor) → dacă auto_publish: publish(actor).
5. publish publică deja COMPLIANCE_BASELINE_PUBLISHED → BaselineConsumer Go
   recompută baseline_effective fleet-wide. Nu se adaugă nimic aici.
```

### Răspuns

```json
{
  "baseline_id": "...", "version_id": "...", "status": "PUBLISHED",
  "per_domain": [
    {"domain": "sshd",    "state": "ADOPTED", "agents_sampled": 12},
    {"domain": "file_integrity", "state": "SKIPPED", "reason": "no snapshots in scope"}
  ]
}
```

### Criterii de acceptanță

- Un apel pe scope GLOBAL produce baseline PUBLISHED acoperind toate domeniile cu snapshot-uri.
- Re-adopt fără schimbări de stare → răspuns `status: UNCHANGED`, zero versiuni noi.
- `auto_publish=false` → versiune PENDING_APPROVAL vizibilă în UI-ul de baselines obișnuit.
- Fiecare pas scrie în audit cu actorul uman inițiator.

---

## S2 — Settings centrale (fără migrări)

Toate comutatoarele Autopilot trăiesc în tabelul de settings existent (`/admin/settings`, deja GET/PUT):

| Cheie | Tip | Default | Efect |
|---|---|---|---|
| `compliance.auto_assessment_days` | int | `0` | `0`=off; `N`≥7 → assessment GLOBAL programat la N zile |
| `compliance.auto_remediation_enabled` | bool | `false` | kill-switch master pt. A2 |
| `compliance.auto_remediation_domains` | JSONB list | `[]` | allowlist domenii eligibile (ex. `["sshd","sysctl"]`) |
| `compliance.auto_remediation_max_severity` | string | `"LOW"` | prag: `LOW`<`MEDIUM`<`HIGH`<`CRITICAL`; doar incidente ≤ prag |
| `compliance.auto_remediation_max_plans_per_day` | int | `10` | limită de siguranță anti-furtună |

Citirea lor se face cache-uit (Redis TTL 60s) — aceeași convenție ca restul settings-urilor.

---

## A1 — Assessment programat

### Mecanism

Worker nou `backend/lokilinux/workers/compliance_assessment_scheduler.py`, tiparul exact al lui `WorkflowSchedulerWorker`:

1. Tick zilnic (3600s check interval, decizie pe calendar day).
2. Citește `compliance.auto_assessment_days`; `0` → exit.
3. Există assessment GLOBAL creat în ultimele N zile? (`SELECT max(created_at) FROM compliance_assessments WHERE scope_selector='{}'`) → da: exit.
4. Altfel: INSERT `ComplianceAssessment(scope_selector={}, policy_set_id=NULL, status=PENDING, created_by=NULL)`.
5. De aici totul e **cod existent**: AssessmentPoller Go îl claim-uiește la 5s, fan-out prin JobService, progres pe servers_done/rules_done.

### Decizii

- `created_by=NULL` + convenție „system assessment" (UI afișează „Automat").
- Nu se programează per-scope în v1 — un singur assessment global e suficient și previne multiplicarea job-urilor.
- Dacă stack-ul e oprit peste interval → assessment pornește la prima ocazie (comportament catch-up natural al check-ului „ultima dată").

### Criterii de acceptanță

- `days=14` → după deploy apare maxim un assessment/14 zile, fără intervenție.
- `days=0` → zero rânduri noi.
- Kill: setezi 0 → următorul tick nu mai creează nimic.

---

## A2 — Auto-remediere safe mode

### Precondiții (toate obligatorii, evaluate în ordine)

```
settings.auto_remediation_enabled == true
ȘI incident drift OPEN/ACKNOWLEDGED
ȘI incident.domain ∈ auto_remediation_domains
ȘI severitate(incident) ≤ auto_remediation_max_severity
ȘI există RemediationTemplate ACTIV pentru rule_key-ul regulii încălcate
ȘI template are rollback_body ne-gol
ȘI există maintenance window activ care include agentul
ȘI nu există alt plan EXECUTING/VERIFYING pe același incident
ȘI contor zilnic plans < auto_remediation_max_plans_per_day
```

### Flux

Extensie minimă în `RemediationSchedulerWorker` (tick existent):

```
pentru fiecare incident eligibil:
  1. creează RemediationPlan(trigger_type=AUTOMATIC, is_emergency=false,
                             actions=[...din template..., drift_event_id=incident.id])
  2. dry-run MANDATORIU: dispatch COMPLIANCE_REMEDIATE cu operation=DRY_RUN
     (check mode ansible nativ) — eșec → plan FAILED, incident rămâne deschis
  3. auto-approve actor system:autopilot (audit)
  4. dispatch real în fereastra de mentenanță găsită mai sus
  5. VERIFYING prin RemediationVerificationWorker existent:
     PASS → _resolve_related_drift închide incidentul (RESOLVED)
     FAIL → plan FAILED + alertă; incident rămâne deschis; NU se reîncearcă
            automat pe același incident în aceeași zi (guard anti-loop)
```

### Garantii de siguranță

- **Niciodată fără dry-run reușit** înainte de aplicare.
- **Niciodată fără rollback_body** — validat la seleția template-ului.
- **Niciodată în afara ferestrei de mentenanță.**
- Plafon zilnic + allowlist domenii + prag severitate = trei supape independente.
- Orice pas automat e etichetat `trigger_type=AUTOMATIC` în UI și audit.

### Criterii de acceptanță

- Setting off → zero planuri automate (test: incident eligible, setting off, nimic).
- Dry-run eșuat → plan FAILED, zero execuție reală.
- Buclă imposibilă: incident RESOLVED de verificare → nu mai e eligibil; FAIL → guard zilnic.

---

## A3 — Conectarea stărilor moarte ale incidentelor

Astazi `IN_REMEDIATION` și `EXCEPTION` apar în filtre dar nimeni nu le setează (verificat: doar `RESOLVED` are writer în `remediation_verification.py:176` și `SUPPRESSED` în `drift.py:205`).

### IN_REMEDIATION

Când un RemediationPlan trece în `EXECUTING`:

```sql
UPDATE drift_events SET status='IN_REMEDIATION'
WHERE id IN (SELECT drift_event_id FROM remediation_actions
             WHERE remediation_plan_id=:plan_id AND drift_event_id IS NOT NULL)
  AND status IN ('OPEN','ACKNOWLEDGED');
```

Punct de inserare: tranziția de status a planului (același loc unde se scrie auditul de tranziție). Dacă planul ajunge FAILED/ROLLED_BACK → incidentele revin `OPEN` (rollback de stare, cu `last_seen=now()`).

### EXCEPTION

Când o compliance exception trece în `APPROVED` (routerul `exceptions.py`, approve):

```sql
UPDATE drift_events SET status='EXCEPTION', suppressed_by=:approver_id
WHERE domain = :rule_domain
  AND agent_id ∈ agenții acoperiți de scope_selector-ul excepției
  AND status IN ('OPEN','ACKNOWLEDGED')
  AND EXISTS (regula încălcată de incident == regula excepției);
```

Legarea incident→regulă există deja: `rule_evaluations` conține verdicturile per (agent, rule); incidentele pe domeniul regulii cu verdict FAIL corespund. Consistență cu dedup-ul Go: `IncrementDriftOccurrence` se potrivește doar pe `OPEN/ACKNOWLEDGED`, deci reapariția abaterii sub excepție deschide incident nou — corect semantic.

### Criterii de acceptanță

- Plan EXECUTING → incidentele legate devin IN_REMEDIATION; ROLLED_BACK → revin OPEN.
- Excepție aprobată → incidentele acoperite devin EXCEPTION; expirarea excepției (Expirer existent) → **nu** redeschide automat vechile incidente (istoria rămâne; următorul snapshot cu FAIL creează incident nou).

---

## Matricea finală de configurare

```
Doresc...                                    │ Setez
---------------------------------------------┼----------------------------------
doar evaluare+drift (stadiul azi)            │ nimic (seed-ul curat e automat)
baseline fără 4 pași                         │ butonul Adopt din UI / S1 API
assessment periodic                          │ auto_assessment_days = 14
remediere automată controlată                │ auto_remediation_enabled=true
                                             │ + domains + max_severity
oprire totală automatizări                   │ toate cheile la 0/false
```

## Riscuri & mitigări

| Risc | Mitigare |
|---|---|
| Adopt îngheață configurații greșite drept „conform" | raport per-domain în răspuns; divergențele din sample apar explicit; baseline-urile rămân versionate + rollback |
| Auto-remediere strică hosturi | dry-run mandatory + rollback_body obligatoriu + fereastră + plafon zilnic + allowlist |
| Assessment storm | un singur assessment global programat; pollerul Go debitează prin job engine existent |
| Stare incident inconsistentă | tranzițiile scrise în aceleași tranzacții cu tranzițiile planului/excepției |

## Ordine implementare

1. **S2** (settings — fundația, S effort)
2. **S1** (adopt — valoare imediată, M)
3. **A1** (assessment programat, M)
4. **A3** (stări moarte, S)
5. **A2** (auto-remediere, L — ultima, după ce restul rulează în producție)

Documentație de actualizat la livrare: `04-compliance.md` (secțiunea Autopilot), README (features), `09-recomandari.md` (bifează stările moarte).
