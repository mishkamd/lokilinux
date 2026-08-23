# 05 — Workflow Engine (modul transversal)

> Documentație generată din cod la commit `77c4220` (v0.3.0 — „Add Workflow Builder engine"), august 2026. Singurul modul care traversează toate cele patru straturi ale platformei.

## Rol

Motorul de workflow automatizează secvențe multi-pași pe flota de servere: patch windows, hardening, remedieri compuse, verificări + rollback. Un workflow e definit ca **YAML declarativ** (`apiVersion: lokilinux/v1`, `kind: Workflow`) cu graf de pași, compilat și validat de backend, versionat, publicat, rulat (manual sau programat), cu aprobări umane, condiții, wait-uri și rollback.

## Compoziție — o piesă în fiecare strat

| Strat | Fișiere | Rol |
|---|---|---|
| **Frontend** | `pages/workflows/index.vue`, `[id].vue`; `stores/workflow.ts` (23K), `workflows.ts` | Builder grafic: noduri/muchii → YAML, validare live, istoric versiuni, monitorizare run-uri |
| **API REST** | `routers/workflows.py` (18 endpoint-uri) | CRUD, validate, versions+publish, dry-run, run, cancel, approve/reject |
| **Servicii backend** | `services/workflow_compiler.py`, `workflow_engine.py` (40K), `workflow_service.py` | Compilare YAML→graf, execuție, persistență |
| **Workeri** | `workers/workflow_runner.py`, `workflow_scheduler.py` | Poller avansare run-uri; declanșare SCHEDULE |
| **Model ORM** | `models/workflow.py` | `workflows`, `workflow_versions`, `workflow_runs`, `workflow_step_runs`, `workflow_audit` |
| **Agent Go** | `internal/modules/workflow_steps_executor.go` + dispatch în `manager.go` | Execuție pași coalescați `WORKFLOW_STEPS` |

## Tipuri de noduri (`schemas/workflow.py:28-73`)

| Categorie | Noduri |
|---|---|
| Structural | `START`, `END` |
| Acțiuni agent | `COMMAND`, `ANSIBLE`, `PACKAGE`, `SERVICE`, `FILE`, `SYSTEM` |
| Control flow | `CONDITION` (branch pe context), `APPROVAL` (gată umană), `WAIT`, `WAIT_FOR_AGENT` |
| Verificare | `CHECK`, `VALIDATION` |
| Integrare | `NOTIFICATION`, `WEBHOOK` |

Triggere: `MANUAL` sau `SCHEDULE`. Fanout agenți: mod `all_at_once`. Edge condition: `on: success` (implicit).

## Cum funcționează

### 1. Compilare și validare (`workflow_compiler.py`)

```
YAML text ──parse_yaml_text()──► WorkflowDocument
          ──validate_graph()──► errors[] + warnings[]
          ──build_graph()─────► CompiledGraph (adiacență, topologie)
compute_content_hash()          hash conținut pentru versiuni
serialize_document()            YAML canonizat
```

Endpoint-uri: `GET /workflows/schema` (schema nodurilor pentru UI) și `POST /workflows/validate`.

### 2. Versionare + publish

Fiecare salvare creează o `WorkflowVersion` nouă (istoric imutabil). Doar versiunile **publicate** pot fi rulate. Politica poate migra la workflow prin `POST /policies/{id}/migrate`.

### 3. Pornirea unui run (`start_run`, `workflow_engine.py:134`)

1. `POST /workflows/{id}/run` (sau scheduler-ul pentru trigger SCHEDULE).
2. Se creează `WorkflowRun` + `WorkflowStepRun` per pas.
3. `dry_run` disponibil: parcurge graful fără efecte, validează configurarea fiecărui pas (`_compile_check/_compile_service/...`).

### 4. Avansarea run-ului (`advance_run`, `workflow_engine.py:584`)

`WorkflowRunnerWorker` poll-ează la **5s** toate run-urile RUNNING și cheamă `advance_run`:

```
advance_run(db, cache, run):
    pentru fiecare step gata de intrare (predecesoare reușite):
        CONDITION   → evaluează contextul (_build_condition_context)
                      alege ramura din graf
        APPROVAL    → trece step în AWAITING_APPROVAL; se oprește până
                      la POST /runs/{run}/steps/{step}/approve|reject
        WAIT        → timer; WAIT_FOR_AGENT → așteaptă satisfacerea
                      agenților țintă (_wait_for_agent_satisfied)
        NOTIFICATION→ publică eveniment NATS (_dispatch_notification)
        WEBHOOK     → HTTP outbound (_dispatch_webhook)
        acțiuni agent (command/ansible/package/service/file/system):
            dacă agenții suportă nativ WORKFLOW_STEPS → job WORKFLOW_STEPS
            coalescat (_agents_support_native); altfel compilează pasul
            la shell CUSTOM_COMMAND (compatibilitate agenți vechi — nu
            există negociere de capabilități în protocol)
    rezultatul job-ului agent → exit code (_step_exit_code) → SUCCESS/FAILED
    END atins sau pas critic eșuat → run COMPLETED/FAILED (+rollback dacă e cazul)
```

De ce poller, nu hook: docstring-ul din `workflow_runner.py` explică — un hook pe `JobService.recompute_job_status` ar crea un FK înapoi spre `jobs` care se poate desincroniza; latența adăugată (≤5s) e neglijabilă față de intervalul de heartbeat (~60s).

### 5. Execuția pe agent

Backendul trimite job-uri `WORKFLOW_STEPS` cu `params.steps[] = [{sequence, type, params}]`. Pe agent, `Manager.runJob("WORKFLOW_STEPS")` → `parseWorkflowSteps()` → `WorkflowStepsExecutor.Execute()` care rulează pașii secvențial (composează AnsibleExecutor + JobExecutor intern). Rezultatul revine în heartbeat-ul următor.

### 6. Aprobări și audit

- `approve_step`/`reject_step` (`workflow_engine.py:772/796`) — actor Better Auth, trecere stări + audit;
- `cancel_run` anulează run-ul activ;
- tabelul `workflow_audit` ține fiecare tranziție semnificativă.

## Dependențe

- Backend: DB (5 tabele), Redis cache, NATS (notificări), Job engine + heartbeat pipeline.
- Agent: doar mecanismul standard de job-uri.
- Frontend: REST workflows + schema nodurilor.

Dependenți: Policy migration (`/policies/{id}/migrate`), Remediation plans (acțiuni similare, executor separat).

## Decizii de design

1. **YAML declarativ + graf validat server-side** — sursa de adevăr e textul versionat; builder-ul UI e confort, nu necesitate.
2. **Pași coalescați într-un singur job `WORKFLOW_STEPS`** — un heartbeat dus-întors per batch de pași, nu per pas.
3. **Compilare defensivă la shell** — pașii service/system/file/package merg azi ca `CUSTOM_COMMAND` până există negociere versiune/capabilități agent-server (documentat explicit în `agent/internal/agent/manager.go:405-421`).
4. **Poller > hook** — simplitate și consistență peste micro-latență.
