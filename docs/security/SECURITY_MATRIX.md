# LokiLinux — Security Matrix

> Data: 2026-08-24 · Stări: Fixed / Mitigated / Accepted Risk / Open(Pn) / Unknown
> Detalii complete per finding: vezi `SECURITY_AUDIT.md`.

| Component | Threat | Severity | Current State | Fix | Status |
|---|---|---:|---|---|---|
| API Jobs | VIEWER creează CUSTOM_COMMAND → RCE root flota | CRITICAL | RBAC insuficient, aprobare off | Matrice job-type la nivel serviciu; ADMIN-only; requires_approval forțat; audit | **Fixed** |
| NATS | Broker deschis — citire/injectare totală | CRITICAL | Fără auth/TLS, 4222+8222 pe host | Auth credențiale + unpublish porturi (agenții nu folosesc NATS) | **Fixed** |
| gRPC | Impersonare agent (cert nelegat de agent_id) | CRITICAL | agent_id self-reported | Interceptor CN/SAN↔agent_id + deny-list revoked | **Fixed** |
| Enrollment | Identity takeover pe hostname | HIGH | Re-emisie cert pentru agent existent | 409 pe hostname existent; re-enrollment doar cu dovada cert vechi/admin | **Fixed** |
| PKI | Fără revocare certs (365z); CA key în volume app | HIGH | Zero CRL/deny-list | P0: deny-list în interceptor. P1: certs short-lived + renewal + CA signing service | Fixed (PR #18); TTL 30z de verificat live |
| Distribution | Artefacte agent nesemnate | HIGH | Zero sha256/sig în agent/bin | sha256+Ed25519 per release; verificare instalatori; curățenie binare străine | Accepted Risk → Open(P1) |
| Plugins | Checksum opțional → RCE root pe flota | HIGH | `checksum or ""` ambele părți | Checksum obligatoriu end-to-end + allowlist origin | Accepted Risk → Open(P1) |
| Workflows/Policy/Plugins | SSRF (webhook step, datastream, source_url) | HIGH | URL arbitrar server-side | Allowlist scheme/host; blocare RFC1918/metadata | Fixed: webhook + datastream (IP guard), plugin (origin allowlist). DNS rebinding TOCTOU rămâne |
| Secrets/.env | Parole slabe + porturi all-interfaces | HIGH | Pattern-guessable | Rotire parole puternice; bind 127.0.0.1 | **Fixed** |
| Compliance ingest | Evenimente forjate → poisoning scoring/incidente | HIGH | BLAKE3 self-check inutil | P0: NATS auth elimină publisher extern. P1: HMAC per-agent ✓ (enforcement off until the fleet reports MACs), stream MaxBytes 4 GiB ✓ (consumer.go:54); Facts size cap and strict schema open | Partial (P1) |
| Containers | Root implicit, fără cap_drop/nnp/read_only | MEDIUM | Toate app containers root | USER non-root; cap_drop ALL; no-new-privileges; distroless:nonroot | Open(P1) |
| Rate limiting | Un bucket/proxy; fail-open; fără body cap | MEDIUM | client.host only | XFF support; fail-closed option; body size middleware | Partial: XFF ✓ (TRUST_PROXY_COUNT; config.py, middleware/rate_limit.py), body cap ✓ per path (middleware/body_limit.py); fail-closed option still absent |
| HTTP headers | Fără CSP/HSTS/XFO/TrustedHost | MEDIUM | Absent complet | SecurityHeadersMiddleware + TrustedHostMiddleware | Partial: headers ✓ (middleware/security_headers.py, main.py); TrustedHosts in log mode by default ✓ (middleware/trusted_hosts.py); enforce after a live check (P1r-1.2) |
| JetStream | Storage exhaustion (fără MaxBytes) | MEDIUM | Doar MaxAge 24h | MaxBytes 4 GiB on COMPLIANCE stream ✓ (consumer.go:54); 10 GiB on EVENTS/SIGNALS/INCIDENTS ✓ (eventbus.py:20-25) | Fixed |
| Signed jobs | Infrastructură Ed25519 inactivă | MEDIUM | enforce_signed_jobs off | Activare + semnare la creare + verificare agent (rebuild flota) | Open(P1) |
| Dependencies | npm fără lockfile în build; ^ floating; cryptography drift | MEDIUM | package-lock ignorat | npm ci + lockfile copiat; cryptography aligned; pip-audit and npm audit in CI | Fixed (P2) |
| Agent config | Token în command line install | LOW | ps/history expunere | Env var or --token-file ✓; --token still works, with a warning | Fixed (P2) |
| Telemetry | IP self-reported | LOW | ip_address din payload | Folosire peer addr ca sursă adevăr | Open(P2) |
| Sessions | Raw token ca Redis key; lag revocare 60s | MEDIUM | ba:session:<token> | Digest of token as key ✓; logout invalidation still open (60s TTL bounds it) | Partial (P2) |
| systemd agent | Sandbox incomplet pe Ubuntu | LOW (Rocky), MEDIUM (Ubuntu) | Toate directivele prezente în cod; PrivateDevices+MemoryDenyWriteExecute live-verificate 2026-08-27 pe Rocky 9.8 (devapp.mishka.md), NRestarts=0, e2e_signed_job.sh 8/8 | Test live pe Ubuntu 22.04/24.04 (fără VM disponibil) | Closed(Rocky) / Open(Ubuntu, P3) |
| Info disclosure | /ready DB exception; auth detail leak | LOW | Excepții raw în răspunsuri | Generic messages + log intern | Partial: /ready ✓, auth detail open |
| Frontend | XSS surface / better-auth config | Unknown | No v-html or innerHTML; component :is only with mapped icons. Better Auth cookie flags use library defaults | Set cookie attributes explicitly after a live login check (P3) | Partial (P3) |

## Verificare runtime necesară după aplicarea fix-urilor

1. Restart stack complet cu `.env` rotit (`docker compose down && up -d`) — toate serviciile preiau credențialele noi.
2. Verificat că compliance consumă snapshot-uri post-auth (JetStream consumer ack-uri cresc).
3. Verificat că agenți existenți se reconectează la gRPC (certs existente rămân valide).
4. Flux re-enrollment testat end-to-end cu un agent real.
