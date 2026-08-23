# 07 — Plugin Ansible Automation (`ansible-automation`)

> Documentație generată din cod la commit `77c4220` (v0.3.0), august 2026.

## Rol

Strat de automatizare AWX-like peste motorul de job-uri: proiecte, roles, playbooks și job templates stocate în DB, lansabile repetat pe flota live. **Inventarul e flota însăși** — nu există fișiere hosts statice; un proiect doar memorează ce agenți țintește implicit.

Modulul e **gated pe plugin**: toate rutele REST depind de `require_plugin_enabled("ansible-automation")` (`routers/playbooks.py:33-51`) — o interogare pe tabelul `plugins`, 403 dacă rândul lipsește sau nu are `is_enabled`. Fără caching deliberat (trafic mic de admin); ciclul de viață al plugin-ului: `PENDING_INSTALL → INSTALLING → INSTALLED → ENABLED` (+ `DISABLED`/`INSTALLING_FAILED`/`ERROR`), gestionat din `/plugins`.

## Compoziție

```
backend/lokilinux/
├── api/v1/routers/
│   ├── playbooks.py             # + definiția gate-ului require_plugin_enabled
│   ├── playbook_templates.py
│   ├── ansible_roles.py
│   └── ansible_projects.py
├── services/
│   ├── playbook_service.py      # CRUD + execute_playbook (snapshot roles → job)
│   ├── playbook_template_service.py  # saved combos + launch/history
│   ├── ansible_role_service.py  # CRUD + snapshot_roles()
│   └── ansible_project_service.py
└── models/
    ├── playbook.py              # playbooks
    ├── playbook_template.py     # playbook_templates
    ├── ansible_role.py          # ansible_roles
    └── ansible_project.py       # ansible_projects

frontend/
├── pages/automation/ansible/{projects,roles,playbooks,templates}/   # index + [id] unde e cazul
└── stores/{playbooks,playbook_templates,ansible_projects,ansible_roles}.ts

agent/internal/modules/ansible_executor.go   # execuție locală securizată (vezi mai jos)
```

## Suprafața REST (`/api/v1`, toate gated)

| Grup | Prefix | Endpoint-uri |
|---|---|---|
| Playbooks | `/playbooks` | CRUD complet + `POST /{id}/execute` → `JobResponse` (201) |
| Templates | `/playbook-templates` | CRUD + `POST /{id}/launch` → job + `GET /{id}/history` (job-urile anterioare) |
| Roles | `/ansible-roles` | CRUD |
| Projects | `/ansible-projects` | CRUD |

## Cele 4 entități

| Model | Tabel | Câmpuri cheie | Reguli |
|---|---|---|---|
| `Playbook` | `playbooks` | `content` (YAML raw), `version`, `role_ids` JSONB, `default_extra_vars` JSONB, `project_id` FK nullable (`SET NULL`), `generated_by` | `version` crește la fiecare editare; `generated_by` = seam pentru asistent AI viitor (azi mereu „user") |
| `AnsibleRole` | `ansible_roles` | `files` JSONB `{cale_relativă: conținut}` (ex. `tasks/main.yml`), `version`, `is_enabled` | Fără filesystem — fișierele trăiesc în DB și se materializează pe agent la execuție |
| `PlaybookTemplate` | `playbook_templates` | `playbook_id` FK (`CASCADE`), `agent_ids`, `extra_vars` | Echivalentul AWX „Job Template"; NU duplică conținutul — rulează mereu versiunea *curentă* a playbook-ului |
| `AnsibleProject` | `ansible_projects` | `name` unique, `default_agent_ids` JSONB | Inventarul = agenții live; proiectul = gruparea playbook-urilor + ținte implicite |

`created_by` e UUID Better Auth fără FK pe toate patru — utilizatorii nu trăiesc în schema backend-ului.

## Fluxul de execuție

```
UI / API
  │ POST /playbooks/{id}/execute        (sau POST /playbook-templates/{id}/launch)
  ▼
PlaybookService.execute_playbook            (services/playbook_service.py:107)
  │ snapshot_roles(playbook.role_ids)       → {nume_role: {cale: conținut}}
  │   doar role-uri is_enabled; SNAPSHOT imutabil embedat în job —
  │   editările ulterioare de roles/playbook NU afectează run-ul pornit
  │ Job(type=ANSIBLE_PLAYBOOK,
  │     target_servers={"agent_ids": [...]},
  │     parameters={playbook_content, extra_vars, roles, timeout})
  ▼
heartbeat-ul agentului ridică job-ul (get_pending_jobs filtrează cele neaprovate)
  ▼
Manager.runJob("ANSIBLE_PLAYBOOK") → AnsibleExecutor.Execute()
```

## Executor-ul pe agent (`agent/internal/modules/ansible_executor.go`)

### Modelul de securitate

1. **Fără shell** — playbook content și extra_vars sunt date nesigure de utilizator; se scriu în fișiere și se transmit lui `ansible-playbook` prin **argv**, niciodată interpolate într-un string shell (contra-exemplu: `JobExecutor` care rulează comenzi arbitrare).
2. **Validare path traversal pe roluri, pe agent** (`writeRoles`, liniile 43-74) — backendul validează la scriere, dar agentul nu are ce avea încredere în payload: nume role fără `/`/`..`, căi relative curățate, respingere `..` prefix. Motivare din cod: *„un control plane compromis nu trebuie să obțină scrieri arbitrare de fișiere"*.
3. **Ieșire din sandbox prin systemd-run** — agentul rulează cu `ProtectSystem=strict`; un playbook chiar are de mutat hostul, deci execuția pornește printr-o unitate tranzientă systemd (`systemd_run.go`) în afara namespace-ului agentului.
4. Output limitat la **4 MB** per run.

### Mecanica

| Pas | Detaliu |
|---|---|
| Verificare binar | `exec.LookPath("ansible-playbook")` — lipsă → job FAILED cu mesaj clar (ansible-core trebuie instalat pe host) |
| Staging | `/var/lib/lokilinux/ansible-tmp/job-<jobID>-*/` — cale reală, nu `/tmp`: unitatea tranzientă nu vede PrivateTmp al agentului |
| Layout | `playbook.yml` + `extravars.json` + `roles/<nume>/<cale>` (0600/0700); roles/ adiacent playbook-ului → ansible le rezolvă automat |
| Invocare | `ansible-playbook -i localhost, -c local -e @extravars.json [--check --diff] playbook.yml` |
| Curățenie | `defer os.RemoveAll(dir)` |

### Check mode

`checkMode=true` adaugă `--check --diff` — dry-run nativ ansible: raportează ce s-ar schimba fără să aplice. E jumătatea ansible a remedierii compliance dry-run (provider ansible din `COMPLIANCE_REMEDIATE`) și e disponibil oricărui apelant al executor-ului.

## Integrări

- **Workflow Engine** — tipul de pas `ANSIBLE` ajunge la același `AnsibleExecutor` pe agent (compus prin `WorkflowStepsExecutor`); pașii pot intra atât în job-uri coalescate `WORKFLOW_STEPS`, cât și ca job-uri `ANSIBLE_PLAYBOOK` dedicate.
- **Remediation** — `RemediationExecutor` compune `AnsibleExecutor` pentru acțiuni cu provider ansible; DRY_RUN trece prin check mode.
- **Plugin System** — dezactivarea plugin-ului blochează imediat CRUD+lansări la poartă REST; job-urile deja pornite își continuă ciclul natural.

## Dependențe

- Motorul de job-uri + heartbeat pipeline (dispatch, aprobări, rezultate).
- Plugin row `ansible-automation` activ.
- `ansible-core` instalat pe fiecare host țintă (verificat la runtime, mesaj de eroare explicit).
- Frontend: 4 store-uri Pinia + paginile `/automation/ansible/*`.

Dependenți: Workflow Engine (pas ANSIBLE), Remediation (provider ansible).

## Decizii de design

1. **DB peste filesystem** — playbooks/roles ca text/JSONB: versionare trivială, backup odată cu DB-ul, zero sincronizare de foldere; prețul: dimensiune rânduri mai mare, fără git history nativ.
2. **Snapshot la execuție** — conținut playbook + roles copiate în job: un run e reproductibil indiferent ce editezi după; identic cu politica workflow versioning.
3. **Gate la poarta REST, nu în worker** — plugin-ul dezactivat oprește crearea job-urilor noi; execuția celor existente rămâne consistentă (fără stări semi-anulate).
4. **argv, nu shell** — întreaga suprafață de injecție a YAML/JSON-ului user dispare prin construcție.
5. **Inventar viu** — `default_agent_ids`/`agent_ids` referențiază agenți reali; niciun hosts file de menținut în sync.
