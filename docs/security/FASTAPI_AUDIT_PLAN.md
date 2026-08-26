# Plan Audit & Optimizare FastAPI Backend

**Dată:** 2026-08-25
**Scope:** `backend/lokilinux/` — componenta FastAPI (~24 routere, ~30 servicii, 19 workers)
**Metodă:** audit static complet (routere, servicii, workers, auth, cache, DB, deps, Docker, CI, teste), findings P0 verificate manual în sursă înainte de includere.

---

## Decizii luate (aprobate)

| Decizie | Alegere |
|---|---|
| Routere nemontate `incidents/signals/correlation` | **Mount** în API v1 |
| NATS plain-core subscribe fără queue groups | **Fix now** — durable consumers pentru handleri cu efecte laterale |
| `rendered_body`/`rollback_body` arbitrar la compliance remediation | **Caps + validation only** (fără breaking API change) |
| Scope | **P0→P7 complet** |
| `AgentResponse` expune recon data la VIEWER | **Role-gated schema** (verificare frontend înainte) |

---

## Findings (rezumat audit)

### P0 — Security (verificate manual)

1. **Shell injection prin `package_name`.** Date agent-reported intră nevalidată în DB (`services/agent_service.py:218-227`) și ajunge randată în shell doar între ghilimele duble (`api/v1/routers/cves.py:58-66`, randare la `cves.py:578-583`). Agent compromis → root shell pe fiecare agent targetat.
2. **Shell injection port check.** `bash -c '</dev/tcp/{host}/{port}'` — `host` nu trece prin `q()` (`services/workflow_engine.py:281`); un `'` în config sparge quoting-ul.
3. **Fail-closed signing anulat.** `_get_signer()` ridică `RuntimeError` când `JOB_SIGNING_REQUIRED=true` + cheie lipsă (`services/job_envelope.py:94-102`), dar `maybe_attach_envelope` înghite tot prin `except Exception: return params` (`job_envelope.py:141-143`) → dispatch unsigned silențios în enforcement mode.
4. **`CUSTOM_COMMAND` lipsește din capability registry** (`job_envelope.py:32-45`) → comenzi shell privilegiate merg fără envelope/capability binding; entry `WORKFLOW_STEPS` este dead.

### P1 — Correctness / security-adjacent

5. Approval claims niciodată emise: `str(job.target_servers[0])` pe JSONB **dict** → KeyError înghițit (`services/job_service.py:334`; model: `models/job.py:41`).
6. Self-approval permis în remediation plans (`services/remediation_service.py:121-168`); contrast: `baseline_service.py:134-135` are guard.
7. VIEWER poate toggle maintenance mode, fără audit (`api/v1/routers/servers.py:229-252`).
8. Oricine autentificat poate anula joburi (`api/v1/routers/jobs.py:249-269`).
9. SSRF: webhook step către URL user-controlled din worker context (`workflow_engine.py:491-504`); import XCCDF către orice `datastream_url`, răspuns necapuit (`api/v1/routers/compliance/policy_engine.py:389-456`).
10. `rendered_body`/`rollback_body`: string arbitrar, providers shell/python/ansible, fără cap (`compliance/remediation.py:134-151`, `schemas/remediation.py:36-43`).
11. Cursor decode invalid → HTTP 500 în loc de 400, ~20 situri (`policy_engine.py:119,304`, `drift.py:74`, `remediation.py:115`, `reports.py:72`, `file_integrity.py:63`, `inventory.py:92`, `workflows.py:76,180,283`, `jobs.py:79`, `policies.py:59`, `servers.py:90`, `baselines.py:55`, `exceptions.py:59`, `assessments.py:66`, `incidents.py:63`, `signals.py:59`).
12. Heartbeat scrie `output` fără size cap (`agent_service.py:371`; contrast: `job_service.py:382-383` cap 50KB).
13. Cache-key injection: input raw concatenat în chei Redis (`cves.py:84,413,439,503`, `jobs.py:56`, `servers.py:67,134,183`).
14. Enrollment token race check-then-invalidate + certs generate după token burn (`agent_install.py:51,481-483`).
15. Secrets plaintext în settings table (smtp_password, ldap_bind_password, nvd_api_key) — `settings_schema.py`.
16. `admin.list_users` înghite erori → "no users" la outage (`admin.py:81-101`); `CreateUserRequest.role` string liber (`admin.py:104-107`).
17. `create_project` fără IntegrityError handling → 500 la FK violation (`categories.py:84-94`).
18. Topology edges fără tenant filter (`topology.py:38`) — latent multi-tenant leak.

### P2 — Event loop blocking

19. `httpx.AsyncClient` creat per operație: `auth/jwks_validator.py:46` (**hot path toate request-urile autenticate**, +2 încercări cu sleep inline), `admin.py:90,120,161,192`, `workflow_engine.py:500`, `workers/notification_worker.py:77`, `workers/cve_enrichment.py:109`, `policy_engine.py:453`.
20. RSA 2048 keygen + CA signing sync pe event loop la enrollment (`agent_install.py:369-417,483`).
21. XCCDF XML parse multi-MB sync în background task (`complianceascode_importer.py:104,141` via `policy_engine.py:435-482`); openpyxl/reportlab sync pe loop (`report_service.py`).
22. CSV export construit sync (`cves.py:392-401`); sync `open()`/`os.path.exists` în endpoint-uri async (`agent_install.py:126,154,165,224,236,264,344,378`).
23. Redis `KEYS` O(N): `cache.invalidate_pattern()` apelat per heartbeat / job status change / CVE write (`cache.py:114-121`, apelanți `jobs.py:169,269` etc.).

### P3 — Performanță / concurență

24. N+1: SELECT-per-rule în importer (`complianceascode_importer.py:244`); condition context per step-run per tick, poller 5s (`workflow_engine.py:507-542`).
25. Heartbeat = 4-6 commit-uri separate (`agent_service.py:98-378`) — non-atomic + pool pressure.
26. Dashboard trend correlated subqueries non-sargable (`dashboard.py:206-254`); dashboard summary ~10 query-uri/request și compliance overview fără cache.
27. Query-uri fără LIMIT (~14 situri: `policy_engine.py:505,611`, `servers.py:164`, `file_integrity.py:36`, `incidents.py:123`, `runbooks.py:30`, `correlation.py:33`, `playbooks.py:63`, `playbook_templates.py:42,120`, `ansible_roles.py:35`, `ansible_projects.py:35`, `cves.py:507`, `jobs.py:203`, `report_service.py:201`).
28. NATS: plain-core subscribe fără queue groups/durables pe toți consumerii side-effectful (`job_executor.py:28`, `alert_processor.py:24`, `notification_worker.py:34`, `policy_worker.py:35`, `plugin_worker.py:27`, `signal_processor.py:43`, `correlation_worker.py:59`, `event_processor.py:37`, `incident_worker.py:43`) → cu >1 replică, procesare multiplă; shutdown nu oprește `workflow_runner/workflow_scheduler/correlation` workers; majoritatea `stop()` fac cancel fără await; `API_WORKERS=4` multiplichă pollerii fără leader election.
29. Events batch publicat secvențial (`events.py:65-77`).

### P7 — Dead code, boilerplate, deps

30. Routere nemontate: `incidents.py`, `signals.py`, `correlation.py` (378 linii) — au workeri + teste în spate → **mount**, nu delete.
31. `db.get_db` duplicat dead (`db.py:50-58`; toate routerele folosesc `dependencies.get_db`).
32. Deps nefolosite: `orjson`, `python-multipart`, `PyJWT`, `protobuf`. PyYAML vine doar transitive din `uvicorn[standard]`. `cryptography` are 3 versiuni diferite (pyproject/Dockerfile/Dockerfile.dev). `BETTER_AUTH_SECRET` injectat în compose dar necitit în cod.
33. Boilerplate măsurat: cursor pagination ×20/16 fișiere · cache get/set ×14/4 fișiere · `AuditService.log(actor_name=...)` ×18/5 fișiere · fetch-or-404 ×45/~20 · `_safe_uuid` ×3 · worker scaffolding ×10 cu stop divergent · 2 registre capabilități paralele deja divergente.
34. Response models lipsă: admin (13 endpoints), agent_install (9), events (2). `AgentResponse` expune `system_users/listening_ports/network_interfaces/block_devices/recent_logs` la VIEWER. Nume/comments înșelătoare: `jwks_validator` face session introspection, nu JWKS.
35. Teste gap: `admin.py`, `policy_engine.py` (cel mai mare router), plugins, playbooks, playbook_templates, categories, ansible_* — zero teste; auth validator + rate-limit middleware netestate. CI: lipsesc ruff/mypy/coverage; cosign cu `|| true`.

---

## Faze implementare

Fiecare fază se termină cu `ruff check` + `mypy` (strict config există) + `pytest` verde. Commit-uri atomice pe grupare logică.

### Faza 0 — Baseline

- Rulez `ruff check`, `mypy`, `pytest` pe starea actuală; documentez starea de plecare. Dacă baseline-ul e roșu din cauze preexistente, le notez și nu le amestec cu fixurile mele.

### Faza 1 — P0 Security

1. `agent_service._sync_vulnerabilities`: validare charset `^[A-Za-z0-9._+-]+$` pe `package_name` la ingest, reject cu log+metrică.
2. `cves.py`: `shlex.quote(pkg)` la randarea `_UPGRADE_CMD`.
3. `workflow_engine.py:281`: `q(host)` + regex host strict + validare port range la compilarea check-ului de port.
4. `job_envelope.py`: propagă `RuntimeError` din `_get_signer()` când `signing_required()`; except îngust doar pe erori de semnare per-job când signing NU e required; adaug `CUSTOM_COMMAND: (EXEC_BASH, CRITICAL)` în registru; elimin entry-ul dead `WORKFLOW_STEPS`.
5. Teste regresie per vector de injecție (package_name malicious, host malicious, signing-required fără cheie).

### Faza 2 — P1 Correctness & AuthZ

1. `job_service.approve()`: extragere corectă primul agent din `target_servers["agent_ids"]` → claims redevin funcționale.
2. Guard self-approval în `remediation_service.approve()` (created_by == approver_id → 403).
3. `servers.py` maintenance toggle → `require_role("ADMIN","OPERATOR")` + `AuditService.log`.
4. `jobs.py` cancel → role gate consistent cu approve.
5. Helper comun `safe_fetch_url()`: scheme allowlist (https implicit), block RFC1918/link-local/169.254.169.254/::1, size cap, timeout — folosit de webhook step (`workflow_engine.py:500`) și datastream import (`policy_engine.py:453`).
6. `rendered_body`/`rollback_body`: validare charset, length cap 64KB (decizie: caps-only, fără breaking change).
7. `parse_cursor()` comun în `schemas/common.py` care ridică 400; înlocuiesc toate cele ~20 site-uri inline.
8. Cap 50KB pe heartbeat `output` (`agent_service._apply_job_results`).
9. Sanitizare cache-keys: validare format cve_id/UUID, segmente variabile escape/hash.
10. Enrollment: `GETDEL` atomic pe token; generare certs ÎNAINTE de invalidarea tokenului.
11. `admin.list_users`: erori httpx/non-200 → 502; enum rol la create_user.
12. `categories.create_project`: IntegrityError → 409.
13. `topology.py:38`: tenant filter pe edges.
14. Request-ID: generat server-side (uuid4) când clientul nu trimite; bind structlog contextvars pentru correlare în toate log-urile request-ului.
15. Global exception handler: `{error, request_id}` JSON; traceback doar server-side.
16. Security headers middleware: HSTS (prod only), X-Content-Type-Options, Referrer-Policy, X-Frame-Options.
17. Note: secrets plaintext în settings table rămâne deschis — necesită decizie de infra (encrypt-at-rest/KMS ref), documentată în THREAT_MODEL, nu fix rapid.

### Faza 3 — P2 Event Loop

1. Un singur `httpx.AsyncClient` în `app.state.http` (timeouts explicite connect/read/write/pool), dependency `get_http`; workers primesc clientul la construcție; closed la shutdown. Înlocuiesc toate cele 8 situri, inclusiv hot path auth.
2. RSA keygen + CA signing → `anyio.to_thread`.
3. XCCDF parse + openpyxl/reportlab rendering → `asyncio.to_thread`.
4. CSV export → streaming sau `to_thread`; file reads `agent_install` → bytes cached la startup / `to_thread`.
5. `invalidate_pattern`: `SCAN` în loc de `KEYS`.

### Faza 4 — P3 Perf & Concurrency

1. Heartbeat = o singură tranzacție (un commit).
2. Importer: bulk prefetch rules (`rule_key IN (...)`), flush odată.
3. Condition context: joined query unică.
4. Dashboard trend GROUP BY rescris; cache TTL_DASHBOARD pe summary + compliance overview.
5. LIMIT/paginare pe cele ~14 query-uri fără bound.
6. NATS durable queue-group consumers pentru workeri side-effectful (decizie: now); `stop()` uniform (`cancel()` + suppress CancelledError + await); shutdown oprește TOȚI workerii.
7. Events batch: publish paralel sau flush unic.

### Faza 5 — Dead Code & Deps

1. Mount `incidents`/`signals`/`correlation` în `api/v1/__init__.py` (decizie) + teste smoke.
2. Delete `db.get_db` (liniile 48-58).
3. Elimin din pyproject: `orjson`, `python-multipart`, `PyJWT`, `protobuf`; pin explicit PyYAML; `cryptography` unificat (pyproject = sursă unică, Dockerfile instalează din proiect).
4. Elimin `BETTER_AUTH_SECRET` din docker-compose env.
5. Corectez docstring-uri/nume înșelătoare (`jwks_validator` → session introspection).

### Faza 6 — Boilerplate Reduction

1. Extract shared helpers: `parse_cursor` (din Faza 2), `cached_response(cache, key, builder, ttl)`, `AuditService.log(user=current_user_dict)` (elimină ×18 extrageri), `get_or_404`, `safe_user_uuid` unic (auth.dependencies), bază `PollingWorker` pentru scaffolding-ul de worker.
2. Un singur registru capabilități: `job_envelope` importă din `capability_rbac`.

### Faza 7 — Response Models & Schemas

1. `response_model` pe admin (13), agent_install (9), events (2).
2. `AgentDetailResponse` role-gated ADMIN/OPERATOR; VIEWER primește schemă redusă — după verificarea dependențelor din `frontend/`.
3. Admin users passthrough → schemă tipizată explicit.

### Faza 8 — Teste & CI Quality Gates

1. Teste noi: admin router, policy_engine router, auth validator (cache hit/negative-cache/breaker), rate-limit middleware inclusiv fail-open, cursoare → 400, regressii P0/P1 (vectori injecție, envelope propagation, claim issuance).
2. CI: joburi ruff + mypy strict + pytest coverage; cosign fără `|| true`; bandit/pip-audit opțional.

---

## Riscuri principale

| Schimbare | Risc | Mitigare |
|---|---|---|
| NATS durable consumers (F4) | Comportament nou la scaling; migrare consumer state | Teste dedicate; rollout cu o replică întâi |
| Role-gated AgentResponse (F7) | Regresie UI frontend | Verific dependențele frontend înainte de schemă |
| Signing propagation strict (F1) | Dispatch blocat dacă KMS misconfigured | E exact garanția cerută în enforcement mode; test fail-closed |
| Mount routere noi (F5) | Suprafață API nouă expusă | Endpoints au deja get_current_user/require_role; smoke tests |

## Verificare finală

- [ ] Contract API păstrat (în afara celor 2 schimbări aprobate: mount routere, role-gated detail schema)
- [ ] pytest + ruff + mypy verde
- [ ] Fără blocking event-loop operations
- [ ] Connection pools reutilizate (HTTP client unic, Redis pool existent, DB pool existent)
- [ ] Authorization object-level unde e cazul
- [ ] Input validated la boundary (ingest package_name, rendered_body, cursori, cache-keys)
- [ ] SSRF protejat (safe_fetch_url)
- [ ] Command execution secured (charset validation + shlex.quote + q())
- [ ] Rate limits + resource limits (caps output/body/export)
- [ ] Structured logging + request_id correlation
- [ ] Security headers + CORS reviewed
- [ ] Deps curate + pins unificate
- [ ] Dead code eliminat / montat conform deciziilor
