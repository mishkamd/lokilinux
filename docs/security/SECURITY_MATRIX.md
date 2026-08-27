# LokiLinux — Security Matrix

> Data: 2026-08-24 · Stări: Fixed / Mitigated / Accepted Risk / Open(Pn) / Unknown
> Detalii complete per finding: vezi `SECURITY_AUDIT.md`.

| Component | Threat | Severity | Current State | Fix | Status |
|---|---|---:|---|---|---|
| API Jobs | VIEWER creează CUSTOM_COMMAND → RCE root flota | CRITICAL | RBAC insuficient, aprobare off | Matrice job-type la nivel serviciu; ADMIN-only; requires_approval forțat; audit | **Fixed** |
| NATS | Broker deschis — citire/injectare totală | CRITICAL | Fără auth/TLS, 4222+8222 pe host | Auth credențiale + unpublish porturi (agenții nu folosesc NATS) | **Fixed** |
| gRPC | Impersonare agent (cert nelegat de agent_id) | CRITICAL | agent_id self-reported | Interceptor CN/SAN↔agent_id + deny-list revoked | **Fixed** |
| Enrollment | Identity takeover pe hostname | HIGH | Re-emisie cert pentru agent existent | 409 pe hostname existent; re-enrollment doar cu dovada cert vechi/admin | **Fixed** |
| PKI | Fără revocare certs (365z); CA key în volume app | HIGH | Zero CRL/deny-list | P0: deny-list în interceptor. P1: certs short-lived + renewal + CA signing service | Mitigated / Open(P1) |
| Distribution | Artefacte agent nesemnate | HIGH | Zero sha256/sig în agent/bin | sha256+Ed25519 per release; verificare instalatori; curățenie binare străine | Accepted Risk → Open(P1) |
| Plugins | Checksum opțional → RCE root pe flota | HIGH | `checksum or ""` ambele părți | Checksum obligatoriu end-to-end + allowlist origin | Accepted Risk → Open(P1) |
| Workflows/Policy/Plugins | SSRF (webhook step, datastream, source_url) | HIGH | URL arbitrar server-side | Allowlist scheme/host; blocare RFC1918/metadata | Accepted Risk → Open(P1) |
| Secrets/.env | Parole slabe + porturi all-interfaces | HIGH | Pattern-guessable | Rotire parole puternice; bind 127.0.0.1 | **Fixed** |
| Compliance ingest | Evenimente forjate → poisoning scoring/incidente | HIGH | BLAKE3 self-check inutil | P0: NATS auth elimină publisher extern. P1: HMAC per-agent + schema + size caps | Mitigated / Open(P1) |
| Containers | Root implicit, fără cap_drop/nnp/read_only | MEDIUM | Toate app containers root | USER non-root; cap_drop ALL; no-new-privileges; distroless:nonroot | Open(P1) |
| Rate limiting | Un bucket/proxy; fail-open; fără body cap | MEDIUM | client.host only | XFF support; fail-closed option; body size middleware | Open(P1) |
| HTTP headers | Fără CSP/HSTS/XFO/TrustedHost | MEDIUM | Absent complet | SecurityHeadersMiddleware + TrustedHostMiddleware | Open(P1) |
| JetStream | Storage exhaustion (fără MaxBytes) | MEDIUM | Doar MaxAge 24h | MaxBytes + alertă | Open(P1) |
| Signed jobs | Infrastructură Ed25519 inactivă | MEDIUM | enforce_signed_jobs off | Activare + semnare la creare + verificare agent (rebuild flota) | Open(P1) |
| Dependencies | npm fără lockfile în build; ^ floating; cryptography drift | MEDIUM | package-lock ignorat | npm ci + lockfile copiat; align cryptography | Open(P2) |
| Agent config | Token în command line install | LOW | ps/history expunere | Token via stdin/file/env injection | Open(P2) |
| Telemetry | IP self-reported | LOW | ip_address din payload | Folosire peer addr ca sursă adevăr | Open(P2) |
| Sessions | Raw token ca Redis key; lag revocare 60s | MEDIUM | ba:session:<token> | Hash token la key; invalidare activă la logout | Open(P2) |
| systemd agent | Sandbox incomplet pe Ubuntu | LOW (Rocky), MEDIUM (Ubuntu) | Toate directivele prezente în cod; PrivateDevices+MemoryDenyWriteExecute live-verificate 2026-08-27 pe Rocky 9.8 (devapp.mishka.md), NRestarts=0, e2e_signed_job.sh 8/8 | Test live pe Ubuntu 22.04/24.04 (fără VM disponibil) | Closed(Rocky) / Open(Ubuntu, P3) |
| Info disclosure | /ready DB exception; auth detail leak | LOW | Excepții raw în răspunsuri | Generic messages + log intern | Open(P2) |
| Frontend | XSS surface / better-auth config | Unknown | Neauditat profund | Audit dedicat frontend | Unknown |

## Verificare runtime necesară după aplicarea fix-urilor

1. Restart stack complet cu `.env` rotit (`docker compose down && up -d`) — toate serviciile preiau credențialele noi.
2. Verificat că compliance consumă snapshot-uri post-auth (JetStream consumer ack-uri cresc).
3. Verificat că agenți existenți se reconectează la gRPC (certs existente rămân valide).
4. Flux re-enrollment testat end-to-end cu un agent real.
