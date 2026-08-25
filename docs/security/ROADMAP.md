# LokiLinux — Security Hardening Roadmap

> Creat: 2026-08-24 · Status: PLAN APROBAT (neexecutat)
> Origine: security audit 2026-08-24 (`SECURITY_AUDIT.md`) — fazele P1r→P3 acoperă restanțele
> după fix-urile P0 și după hardening-ul de container/semnare deja livrat.

## Decizii de design înregistrate

| Decizie | Alegere |
|---|---|
| Execuție remote pe agenți | Rămâne BY DESIGN, cu hardening + gating (ADMIN-only, aprobare, audit, semnare) — nu se elimină din produs |
| Rollout modificări agent Go | Build + test local; rollout-ul pe fleetă e operațiune separată, ulterioară |
| Compatibilitate flota veche | Server-side backward-compatible: funcțiile noi (HMAC verify, cert renewal) se activează doar pentru agenți care raportează versiunea nouă (pattern `_agents_support_native()`) |
| Scope | Full plan (P1r-1..4 + P2 + P3), ~19h |

---

## Starea de plecare (verificată la crearea planului)

### Fixed (audit P0 + sesiune concurentă)
- CR-01 jobs RBAC matrice + approval forțat · CR-02 NATS auth + unpublish · CR-03 cert↔agent_id binding · HI-01 enrollment proof-of-possession
- Artefacte agent semnate (.sig la packaging, verificate la instalare) · plugin gate Ed25519 bound la digest
- Containere non-root (`USER appuser`/`nonroot`/`nuxt`) · compose hardening (security_opt, cap_drop, pids, read_only) · rețea segmentată `app-net`
- systemd hardening extins + sandbox profiles per-capabilitate pe job-uri tranziente
- RBAC pe capabilități pentru creare job-uri cu audit pe deny
- `npm ci` reproducibil în build frontend

### Open (acoperit de acest plan)
SSRF guards · headers HTTP/body cap/XFF rate-limit · JetStream MaxBytes · HMAC events + Facts caps · certs short-lived + CA izolat + endpoint revocare · sesiuni hash-key în Redis · secret mort · IP truth · token CLI · crypto drift · CSV escape · echo parolă docker-init · binare străine · CI security scanning · audit frontend · contract AI boundary

---

## Faza 1 · P1r-1 HTTP hardening (~2h, risc regresie mic)

**Fișiere**: `backend/lokilinux/main.py`, `backend/lokilinux/middleware/security_headers.py` (nou), `middleware/request_size.py` (nou), `middleware/rate_limit.py`

| # | Acțiune | Detaliu |
|---|---|---|
| 1.1 | SecurityHeadersMiddleware | HSTS, X-Content-Type-Options nosniff, X-Frame-Options DENY, Referrer-Policy strict-origin-when-cross-origin; CSP pentru răspunsuri HTML |
| 1.2 | TrustedHostMiddleware | Allowlist din settings (`PLATFORM_HOSTNAME`); reject 400 altfel |
| 1.3 | Body-size cap | 10MB default; 64KB pe `/auth/*` și `/api/v1/agents/register`; răspuns 413 |
| 1.4 | Rate-limit XFF-aware | Key pe IP real când `X-Forwarded-For` present ȘI `TRUST_PROXY_COUNT>0` (env, explicit — fără trust orb) |
| 1.5 | Erori generice | `/ready`: fără excepție DB în body (LO-01); auth detail → doar log |

**Verificare**: teste noi — headers prezente, oversized body→413, host străin→400, proxy count=1 rezolvă XFF corect, viewer neafectat de limite normale.

## Faza 2 · P1r-2 SSRF guard centralizat (~2h, risc mediu)

**Fișiere**: `backend/lokilinux/utils/url_guard.py` (nou) + apelatori `workflow_engine.py` (webhook step ~:491), `policy_engine.py` (datastream import ~:389), `plugin_service.py` (~:102)

| # | Acțiune | Detaliu |
|---|---|---|
| 2.1 | `assert_safe_url(url)` | scheme http(s) only; deny loopback/RFC1918/link-local/169.254.169.254/::1/0.0.0.0; rezolvare DNS→IP verificat ANTI-REBINDING (verificăm IP-urile rezolvate, nu hostname-ul); fără redirect-uri spre interne (follow cu re-verificare) |
| 2.2 | Allowlist per caz | webhook: settings `WEBHOOK_ALLOWED_HOSTS` (gol=deny all); datastream: idem; plugin origin: PLATFORM_URL implicit |
| 2.3 | Timeout-uri fixe | Elimină timeout-ul user-controlled din webhook step |

**Verificare**: unit tests pe guard (metadata, rebinding, redirect intern, IPv6 forms) + regresie pe cei 3 apelatori.

## Faza 3 · P1r-3 Integritate evenimente + JetStream (~3h, risc mediu, atinge agentul Go)

**Fișiere**: `compliance_ingest_service.py`, `services/compliance/internal/ingest/{consumer,ingest}.go`, `agent/internal/...` (heartbeat payload), `agent/internal/config`

| # | Acțiune | Detaliu |
|---|---|---|
| 3.1 | HMAC-SHA256 per snapshot | Cheie derivată la enrollment (stocată DB + config agent); consumerul Go verifică **doar dacă snapshot poartă HMAC** (backward-compat fail-open pentru agenți vechi; flag enforcement mode pentru post-rollout complet) |
| 3.2 | BLAKE3 rămâne fast-check | Self-consistency, nu securitate |
| 3.3 | Facts schema strictă | Câmpuri/tipuri cunoscute per domain; cap 256KB/snapshot; violații → reject permanent (Term), nu retry |
| 3.4 | JetStream limits | Stream `COMPLIANCE`: `MaxBytes=10GB`, `DuplicateWindow=5m` |

**Build local**: agent Go cu semnare HMAC; teste round-trip server-side cu payload semnat/nesemnat/mârlan.
**⚠️ Rollout separat**: activarea enforcement mode = decizie ulterioară, după upgrade-ul flotei.

## Faza 4 · P1r-4 PKI: certs scurt-lived + CA izolat (~4h, risc mare, atinge agentul Go)

**Fișiere**: `agent_install.py`, `grpc_server.py`, nou `cert-issuer` service sau RPC intern, `agent/internal/communication/grpc_client.go` + renewal logic

| # | Acțiune | Detaliu |
|---|---|---|
| 4.1 | TTL 30 zile | `agent_install.py:387`; NOII agenți primesc certs scurte; cei existenți rămân pe cele vechi până la re-enroll/upgrade (zero downtime) |
| 4.2 | Renewal endpoint | Autentificat cu CERT-UL curent (nu enrollment token): validează chain+CN→agent_id, emite pereche nouă; rate-limit stricte |
| 4.3 | CA key izolare | Scoasă din `certs_dir` partajat → serviciu signing dedicat (container separat, network intern); api/grpc nu văd niciodată cheia |
| 4.4 | Endpoint revocare | ADMIN-only `POST /api/v1/agents/{id}/revoke` → wire `revoke_agent_identity()` (există deja în servicer) + `unrevoke` |
| 4.5 | Renew transparent agent | Agent cere renew când expiry < 7z înainte de conectare (Go, build local) |

**⚠️ Dependențe**: fereastră mentenanță pentru mutarea CA key; rollout agent pentru renew automat.

## Faza 5 · P2 Consolidare (~4h total, risc mic)

| Item | Fișier | Acțiune |
|---|---|---|
| Sesiuni hash-key | `auth/jwks_validator.py:28` | Key = sha256(token), nu raw; purge la logout |
| Secret mort | `config.py:37` | Elimină `better_auth_secret` dacă rămâne nefolosit (verificat: unused) |
| IP truth | `api/grpc/agent_service.py` | Peer addr gRPC ca sursă; ignoră self-report |
| Token CLI | `install_agent.sh.tmpl` + `scripts/install-agent.sh` | Token via stdin/file 0600, nu argv |
| Crypto drift | Dockerfile vs pyproject | Align versiuni (acum 50.0.0 vs 46.0.3!) |
| CSV injection | `cves.py` export | Escape `=+-@` prefixuri |
| Echo parolă | `scripts/docker-init.sh:141` | Suppress plaintext output |
| Binare străine | `agent/bin/` | Șterge `-debug/-old/-new` din distribuție |
| CI security scanning | `.github/workflows/security.yml` (nou) | gitleaks + pip-audit + npm audit + trivy + semgrep pe PR |

## Faza 6 · P3 Frontend + AI boundary (~4h)

| # | Acțiune | Livrabil |
|---|---|---|
| 6.1 | Audit XSS Vue/Nuxt | grep v-html/dynamic component/render; raport + fix-uri |
| 6.2 | Better-auth cookies | Secure/SameSite/HttpOnly flags verificate în config frontend |
| 6.3 | AI boundary contract | `docs/security/AI_BOUNDARY.md` — telemetrie = UNTRUSTED input; AI = recomandări only; READ tools default; execuție doar prin pipeline-ul de job-uri existent (aprobat + semnat) |

---

## Verificare globală (după fiecare fază + final)

```text
1. pytest backend full suite verde (+ ~25 teste noi cumulative)
2. ruff clean pe fișierele modificate
3. go test ./... pe agent + compliance (fazele 3-4)
4. docker compose config valid
5. Smoke E2E: enroll → heartbeat → CUSTOM_COMMAND (ADMIN+aprobare) → execuție → audit trail
6. docker compose up -d --force-recreate pe serviciile atinse
```

## Ordine de execuție și independență

Fazele sunt independente între ele — oricare poate fi întreruptă/reluată. Ordinea optimizază scăderea riscului de regresie: HTTP (adițional, pur middleware) → SSRF (guard izolat) → events (dual-mode) → PKI (cea mai invazivă) → P2 (cosmetic) → P3 (docs).

## Riscuri reziduale rămase după plan

| Risc | Tratament |
|---|---|
| Agenți vechi fără HMAC/renewal până la rollout | Fail-open temporar, monitorizat; enforcement mode după upgrade |
| Suprafața frontend necunoscută până la faza 6 | Audit dedicat în plan |
| Compromitere host LokiLinux (control-plane) | Poate citi tot; mitigat parțial de CA izolare + signed jobs; risc structural acceptat, documentat în THREAT_MODEL |
