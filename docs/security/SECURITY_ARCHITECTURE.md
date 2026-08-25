# LokiLinux — Security Architecture (țintă)

> Data: 2026-08-24 · Starea țintă după P0 (implementat) + P1 (planificat).

## Principii

1. **Never trust, always verify** — niciun hop intern nu e „trusted by default".
2. **Identitate criptografică** — agent_id legat de certificat, nu de hostname/IP/self-report.
3. **Least privilege per componentă** — conturi separate NATS/DB cu permisiuni minimale.
4. **Execuție remote = privilegiu suprem** — ADMIN-only, aprobare obligatorie, audit, semnare.
5. **AI = untrusted decision engine** — doar recomandări; input telemetrie = UNTRUSTED (prompt injection surface); execuția niciodată direct din AI.

## Arhitectura implementată (P0)

```text
                    ┌─────────────────┐
                    │   Admin Panel   │ Nuxt :3000 (proxy public)
                    └────────┬────────┘
                             │ HTTPS + Bearer
                             ▼
                    ┌─────────────────┐
                    │    FastAPI      │ RBAC: ADMIN > OPERATOR >
                    │ Auth + RBAC     │ AUDITOR > VIEWER
                    │ job-type matrix │ CUSTOM_COMMAND: ADMIN + approval
                    └──────┬─────┬────┘
              credențiale  │     │  SQLAlchemy (pgBouncer SCRAM)
                           ▼     ▼
                  ┌──────────┐  ┌──────────────┐
                  │   NATS   │  │ TimescaleDB  │
                  │ AUTH ON  │  │ via pgBouncer│
                  │ NO host  │  └──────────────┘
                  │ ports    │
                  └────▲─────┘
                       │ snapshot pub/sub (autentificat)
                  ┌────┴────────────┐
                  │ lokilinux-      │ Go, distroless
                  │ compliance      │
                  └─────────────────┘

        ┌──────────────── gRPC :50051 mTLS ────────────────┐
        │  INTERCEPTOR: cert CN/SAN ↔ agent_id binding     │
        │  + deny-list revoked agents                      │
        └──────────────────────┬───────────────────────────┘
                               ▼
                  ┌───────────────────────────┐
                  │     LokiLinux Agent (Go)  │ root by design
                  │ Collector→Normalizer→     │ TLS 1.3, RootCAs pinned
                  │ Checks→Publisher          │ systemd sandbox (P2 extins)
                  └───────────────────────────┘
```

## Decizii de design P0

### D1 · Execuția remote rămâne, dar gated (decizie produs)
CUSTOM_COMMAND este funcție centrală a produsului (remediere automată). Eliminarea ar distruge valoarea. Compromisul securizat:
- Creare: ADMIN only (matrice la nivel de serviciu, nu doar router).
- Execuție: `requires_approval=True` forțat — un al doilea actor trebuie să aprobe.
- Audit: creare/aprobare/execuție/rezultat în audit log.
- P1: semnătură Ed25519 pe job (infrastructura există deja) → agentul respinge job-uri nesemnate chiar dacă DB-ul e compromis.

### D2 · Identitate = certificat ↔ agent_id
Interceptorul gRPC extrage certificatul peer (`auth_context.get_auth_context()` key `x509_pem_cert`), parsează CN/SAN și îl compară cu `agent_id` din request. Mismatch → UNAUTHENTICATED. Revocare = flag în Redis checked la conectare. P1: certs short-lived cu renew transparent pe heartbeat.

### D3 · Enrollment fără takeover
Hostname-ul NU mai e cheie de identitate. Token nou → identitate nouă. Re-enrollment pe același host → flux separat care cere dovada posesiunii cert-ului vechi (sau acțiune ADMIN explicită).

### D4 · NATS nu e expus, agenții nu-l văd niciodată
Agenții comunică exclusiv prin gRPC mTLS. NATS rămâne bus intern backend↔compliance cu credențiale obligatorii și zero porturi publicate pe host. P1: accounts separate per serviciu cu subject permissions granulare + TLS intern.

## Arhitectura țintă P1 (roadmap)

| Zonă | Țintă |
|---|---|
| PKI | Agent certs 30z cu renew pe heartbeat; CA key într-un signing container dedicat; deny-list persistă |
| Job signing | Ed25519 semnat la creare, verificat în agent înainte de execut; `enforce_signed_jobs=true` default |
| Plugins | checksum_sha256 obligatoriu (gol → respins), origin allowlist, eventual signed artifacts |
| SSRF | Middleware utilitar `assert_safe_url()` pentru webhook/datastream/source_url |
| Events | HMAC per-agent pe snapshots + validare schema strictă + size caps Facts |
| Containers | USER non-root peste tot, cap_drop [ALL], no-new-privileges, read_only unde posibil, distroless:nonroot |
| HTTP | SecurityHeadersMiddleware, TrustedHostMiddleware, body-size cap, rate-limit XFF-aware |

## Flux de control post-P0 (job execution)

```text
ADMIN creează CUSTOM_COMMAND
   → job_service verifică rol (ADMIN)            [refuz altfel]
   → forțează requires_approval=True
   → audit_log(job.created)
OPERATOR/ADMIN aprobă
   → audit_log(job.approved)
Agent heartbeat → pending_jobs (după bind cert↔id)
   → execută ca root (by design)
   → JobResult → audit trail complet
```
