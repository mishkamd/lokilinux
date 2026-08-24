# LokiLinux — Security Audit

> Data audit: 2026-08-24 · Metodă: revizuire manuală a codului + configurației, subagenți de explorare pe componente.
> Legenda stare: CONFIRMAT (dovadă în cod/config) · Potential (necesită verificare runtime) · Fixed / Mitigated / Accepted Risk.

## Executive Summary

Platforma are fundații bune (mTLS pe gRPC, SQL integral parametrizat, YAML SafeLoader, `.env` curat în istoricul git, pip pins exacte), dar starea generală pre-fix era slabă: **3 CRITICAL, 7 HIGH**. Combinația critică: orice cont VIEWER putea obține RCE root pe toată flota (CR-01), brokerul NATS era complet deschis (CR-02), iar identitatea agentului nu era legată de certificat (CR-03).

Notă de arhitectură: spec-ul inițial menționa ClickHouse și LangGraph — **nu există în repo**. DB = TimescaleDB; componenta AI nu există încă. Agentul rulează ca root BY DESIGN cu execuție remote (decizie de produs confirmată: hardening + gating, nu eliminare).

## Scor pe componente (pre-fix → post-fix P0)

| Componentă | Pre-fix | Post-P0 | Justificare |
|---|---:|---:|---|
| Agent Security | 3/10 | 5/10 | gating server-side activ; signed-jobs end-to-end rămâne P1 |
| API Security | 2/10 | 6/10 | RBAC jobs reparat; SSRF/headers rămân P1 |
| NATS Security | 1/10 | 7/10 | auth obligatorie + porturi nepublicate; TLS intern + accounts granulare P1 |
| DB Security | 5/10 | 7/10 | parole rotite, porturi bind locale; SQL era deja sigur |
| AI Security | N/A | N/A | componentă inexistentă; calea de poisoning documentată |
| Container Security | 3/10 | 3/10 | P1/P2 (USER, cap_drop, read_only) |
| Supply Chain | 3/10 | 4/10 | documentat; semnare artefacte P1 |
| Authentication | 5/10 | 7/10 | enrollment takeover reparat; token-in-Redis rămâne M |
| Authorization | 2/10 | 7/10 | matrice job-type + approval enforcement |
| **Overall** | **3/10** | **6/10** | |

---

## Critical Findings

### CR-01 · VIEWER → RCE root pe flota prin CUSTOM_COMMAND — **Fixed**
- **Locație**: `backend/lokilinux/api/v1/routers/jobs.py` (create endpoint), `backend/lokilinux/services/job_service.py` (`requires_approval: bool = False`), `agent/internal/agent/manager.go:459-469` (orice job_type cu parametrul `command` cade în shell-exec).
- **Vector**: POST `/api/v1/jobs` cu `job_type=CUSTOM_COMMAND`, parametri arbitrari — doar `get_current_user`, fără rol, fără aprobare.
- **Impact**: RCE root pe orice agent din flota; pivot lateral pe toate serverele monitorizate.
- **Fix implementat**: matrice permisiuni pe job-type la nivel de serviciu; `CUSTOM_COMMAND` → ADMIN only + `requires_approval=True` forțat + audit entry.
- **Rezidual**: execuția rămâne by design pentru ADMIN cu aprobare; semnarea end-to-end a job-urilor (Ed25519, infrastructura există) → P1.

### CR-02 · Broker NATS complet deschis — **Fixed**
- **Locație**: `docker-compose.yml:83-89` (doar `--js --sd --m`; porturi 4222+8222 publicate pe host); toate URL-urile `nats://nats:4222` fără credențiale.
- **Vector**: orice host cu reach network citește/injectează orice subject (job results cu stdout/stderr, snapshot-uri compliance, alerte).
- **Impact**: exfiltrare telemetrie + otrăvire pipeline compliance/incidente (vezi HI-07).
- **Fix implementat**: auth credențiale obligatorii pe broker; clienți actualizați; porturile 4222/8222 scoase complet de pe host (agenții NU folosesc NATS — doar gRPC, confirmat).

### CR-03 · Identitate gRPC nelegată de certificat — **Fixed**
- **Locație**: `backend/lokilinux/api/grpc/agent_service.py:93` (`request.agent_id` luat de pe fir); `grpc_server.py:37` (singurul „interceptor" = substring match pe metodă); zero `auth_context`/`peer_identities`.
- **Vector**: orice cert de agent valid impersonifică oricare alt agent_id → îi trage job-urile pending (inclusiv comenzi), postează rezultate false.
- **Fix implementat**: interceptor care extrage certificatul peer din auth context, parsează CN/SAN, compară cu `agent_id` cerut; mismatch → UNAUTHENTICATED; check deny-list revoked agents.

## High Findings

### HI-01 · Identity takeover la enrollment — **Fixed**
- `agent_install.py:309-337`: `POST /agents/register` căuta `Agent.hostname == body.hostname` și re-mintea cert/key pentru agent_id-ul existent. Un singur token furat = identitatea oricărui agent.
- **Fix**: hostname existent → 409; re-enrollment doar prin flux explicit cu dovada vechiului cert sau acțiune ADMIN. Token nou creează identitate nouă.

### HI-02 · Fără revocare certs + CA key expusă containerelor — **Mitigated (P0), restanță P1**
- Certs RSA2048/365zile, zero CRL/OCSP/deny-list; `certs_dir` montat ro în api/grpc/compliance — compromiterea oricăruia = emitere certs noi.
- **P0**: deny-list Redis verificată în interceptorul gRPC (revocare efectivă la conectare). **P1**: certs short-lived + renew pe heartbeat + mutarea CA key într-un serviciu dedicat de signing.

### HI-03 · Lanț distribuție agent nesemnat — **Accepted Risk (documentat), fix P1**
- `agent/bin/` ~120 artefacte fără `.sha256`/`.sig`; `/download-latest` public; binare străine `-debug/-old/-new` servite.
- **P1**: sha256+semnătură Ed25519 publicate per release; verificare în ambii instalatori; curățenie binare.

### HI-04 · Plugin install = lanț RCE root — **Accepted Risk (documentat), fix P1**
- Backend `plugin_service.py:111` acceptă `checksum or ""`; agent `plugin_installer.go:88` sare verificarea dacă checksum gol; download ca root din URL arbitrar.
- **P1**: checksum obligatoriu end-to-end (respins dacă gol), allowlist URL la origin, eventual signing.

### HI-05 · SSRF ×3 — **Accepted Risk (documentat), fix P1**
- `workflow_engine.py:491-500` (webhook step URL arbitrar), `policy_engine.py:389-427` (datastream fetch 120s), `plugin_service.py:102-113` (source_url fan-out către flota). Metadata IP 169.254.169.254 atingibilă. Autori = ADMIN/OPERATOR, deci pre-condition privilegiat.
- **P1**: allowlist scheme+host, blocare RFC1918/link-local/metadata, DNS rebinding protection.

### HI-06 · Parole slabe `.env` + porturi expuse — **Fixed**
- POSTGRES/REDIS/TIMESCALE/ADMIN parole pattern-guessable; porturi 6432/6379/8000/9090/3000 publicate pe all-interfaces.
- **Fix**: rotire parole puternice random; `127.0.0.1:` prefix pe pgbouncer/redis/metrics/api; frontend lasat pe decizia proxy-ului (documentat).

### HI-07 · Evenimente forjate trec BLAKE3 self-check — **Partially Mitigated, restanță P1**
- `ingest.go:106-115`: hash self-claimed de publisher; cu NATS deschis (CR-02) forjarea era trivială → drift_events, rule_evaluations, scores, incidents.
- **P0**: CR-02 elimină publisherul neautentificat. **P1**: HMAC/signature per event cu cheie per-agent + schema validation + size caps pe Facts.

## Medium Findings

| ID | Titlu | Locație | Stare |
|---|---|---|---|
| ME-01 | Containere app rulează root implicit; zero cap_drop/no-new-privileges/read_only; compliance distroless dar nu `:nonroot` | Dockerfiles + compose | Open (P1) |
| ME-02 | Rate-limit pe client.host doar, fail-open; lipsă body-size cap REST | middleware/rate_limit.py | Open (P1) |
| ME-03 | Zero security headers, zero TrustedHostMiddleware | main.py | Open (P1) |
| ME-04 | JetStream fără MaxBytes; Facts `map[string]any` fără schema/size-cap | consumer.go:42-49, ingest.go | Open (P1) |
| ME-05 | npm install ignoră lockfile în build; deps `^` floating frontend; cryptography drift 49.0.0(Dockerfile) vs 46.0.3(pyproject) | frontend/Dockerfile, pyproject.toml | Open (P2) |
| ME-06 | Enrollment token în command line shell (`--token={token}`) | install_agent.sh.tmpl | Open (P2) |
| ME-07 | `ip_address` self-reported peste adresa peer reală | api/grpc/agent_service.py:77-82 | Open (P2) |
| ME-08 | Sesiuni cache-uite în Redis pe raw token; lag revocare 60s | auth/jwks_validator.py:28 | Open (P2, hash key) |
| ME-09 | systemd unit incomplet întărit (lipsesc ProtectKernel*, PrivateDevices, MemoryDenyWriteExecute, SystemCallArchitectures, RestrictNamespaces, RestrictSUIDSGID) | scripts/install-agent.sh + tmpl | Open (P2) |
| ME-10 | Infrastructura signed-jobs Ed25519 existentă dar inactivă | init-certificates.sh, settings | Open (P1) |

## Low Findings

| ID | Titlu | Stare |
|---|---|---|
| LO-01 | `/ready` returnează excepție DB anonim; detail-uri upstream în răspunsuri auth | Open (P2) |
| LO-02 | `better_auth_secret` cerut dar niciodată folosit (secret mort) | Open (P2) |
| LO-03 | `version` nesanitize în `os.path.join` (admin-only) | Open (P2) |
| LO-04 | Redis healthcheck trece parola în argv | Open (P2) |
| LO-05 | `docker-init.sh` echoează parola admin plaintext | Open (P2) |
| LO-06 | CSV formula injection minor la export CVE | Open (P3) |
| LO-07 | Binare străine `-debug/-old/-new` servite public din /downloads | Open (P2) |

## Confirmate BINE (nu se modifică)

- mTLS enforced pe gRPC (`require_client_auth=True`).
- Agent TLS: min TLS 1.3, RootCAs pool pinned, ServerName setat, **zero InsecureSkipVerify**.
- SQL 100% parametrizat (SQLAlchemy bound params; pgx `$n`; zero sprintf în postgres.go).
- `yaml.SafeLoader` peste tot; `utils/expr.py` eval AST-whitelisted solid (fără Call nodes, dunder-blocked, builtins goale).
- Audit-log masking corect (`settings_schema.py` SECRET_KEYS).
- `.gitignore` + istoric git curat — zero secrets comise vreodată (verificat full-history).
- pip pins exacte; go.mod fără replace directives.
- Compliance Go: pgx parametrizat, zero exec.Command, WorkQueue consumer igienic (MaxDeliver, BackOff, Term).
- Resource limits compose prezente pe toate serviciile.
- Plugin installer agent-side: path traversal protejat (`filepath.Base` check), download atomic rename.

## Rezumat supraveghere post-fix

| Categorie | Fixed | Mitigated | Accepted Risk | Needs Verification | Unknown |
|---|---:|---:|---:|---:|---:|
| Critical | CR-01, CR-02, CR-03 | HI-02 (parțial) | — | CR-02 runtime (restart stack) | — |
| High | HI-01, HI-06 | HI-07 (parțial) | HI-03, HI-04, HI-05 | HI-01 (flux re-enrollment E2E) | — |
| Medium/Low | — | — | — | toate P1–P3 în backlog | XSS surface frontend (neauditat profund) |

**NU declarați platforma „secure".** Starea post-P0 = riscuri critice eliminate, riscuri high parțial mitigated sau acceptate explicit cu plan P1. Suprafața frontend (XSS, better-auth config) nu a fost auditată în profunzime — marcată Unknown.
