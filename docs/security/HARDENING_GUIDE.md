# LokiLinux — Hardening Guide (backlog P1/P2)

> Data: 2026-08-24 · P0 implementat — vezi `SECURITY_AUDIT.md` pentru starea curentă.
> Fiecare item: beneficiu securitate vs cost (CPU/RAM/rețea/disk/complexitate).

## P1 — High

### H-1 · Signed jobs end-to-end
Infrastructura Ed25519 există (`init-certificates.sh` generează perechea). Pași:
1. Semnare la creare în `job_service.py` (payload = job_id+agent_id+type+params+created_at).
2. Distribuție public key către agenți (heartbeat response sau config).
3. Verificare în `agent/internal/agent/manager.go` înainte de orice exec; respingere job nesemnat.
4. `enforce_signed_jobs=true`.
Cost: semnare ~µs, zero overhead runtime relevant. Beneficiu: chiar și cu DB compromis, comenzi arbitrare nu pot fi injectate.

### H-2 · Certs short-lived + renewal
1. Reducere TTL la 30 zile (`agent_install.py:310`).
2. RPC/endpoint de renewal autentificat cu cert-ul existent (renew cu 7 zile înainte de expirare).
3. CA key mutată din `certs_dir` partajat într-un container signing dedicat; api/grpc primesc doar cert intermediar.
Beneficiu: fereastră de abuz 365z→30z. Cost: renewal logic + monitoring expiry.

### H-3 · Artefacte distribuție semnate
1. Makefile `agent-package`: generare `.sha256` + `.sig` Ed25519 per artefact.
2. `install.sh` + `/download-latest`: verificare înainte de instalare.
3. Ștergere binare străine (`-debug/-old/-new`) din `agent/bin/`.
4. Public key embedded în instalator.
Beneficiu: lanț supply integru. Cost: ~0.

### H-4 · Plugin checksum obligatoriu
1. Backend: `plugin.checksum` gol → install refuzat (nu `or ""`).
2. Agent: `wantSum == "" → fail("checksum required")` (`plugin_installer.go:88`).
3. Origin allowlist pe download_url (doar platform origin by default).

### H-5 · SSRF guard centralizat
Utilitar `assert_safe_url(url)` folosit de webhook step / datastream import / plugin source_url:
- scheme http(s) only, host allowlist configurabil, deny RFC1918/127.0.0.0/8/169.254.0.0/16/::1/0.0.0.0, rezolvare DNS la IP pentru check (anti-rebinding), timeout fix.

### H-6 · Container hardening
```yaml
# per serviciu app
user: "10001:10001"
cap_drop: [ALL]
security_opt: ["no-new-privileges:true"]
read_only: true            # unde posibil (+ tmpfs pentru /tmp)
```
Backend Dockerfile: adăugare `USER app`. Compliance: `gcr.io/distroless/static-debian12:nonroot`.

### H-7 · Event integrity (compliance ingest)
HMAC-SHA256 per-agent pe snapshot-uri (cheie derivată din enrollment) + validare schema strictă pe Facts (tipuri+câmpuri cunoscute) + size cap per snapshot (ex. 256KB) + JetStream `MaxBytes=10GB`.

### H-8 · HTTP hardening
SecurityHeadersMiddleware (CSP strict pentru frontend prin proxy, HSTS, XFO DENY, XCTO nosniff, Referrer-Policy); TrustedHostMiddleware cu lista domeniilor; body-size limit middleware (ex. 10MB default, mai puțin pe auth); rate-limit XFF-aware cu trust-proxy explicit.

## P2 — Medium

| Item | Acțiune |
|---|---|
| ME-05 deps | `COPY package-lock.json` + `npm ci`; align cryptography pyproject↔Dockerfile; dependabot/renovate |
| ME-06 token CLI | Token via stdin sau file 0600, nu argv |
| ME-07 IP truth | Ignoră ip_address client; folosește peer addr gRPC |
| ME-08 sessions | Redis key pe hash(token); purge la logout |
| ME-09 systemd | Adaugă incremental, testând după fiecare grup: PrivateDevices, ProtectKernelTunables/Modules/Logs, ProtectControlGroups, RestrictSUIDSGID, RestrictRealtime, LockPersonality, MemoryDenyWriteExecute, RestrictNamespaces, SystemCallArchitectures=native, UMask=0077 |
| LO-01 errors | Mesaje generice clienți, detail doar în log |
| LO-02 dead secret | Elimină `better_auth_secret` din backend config dacă rămâne nefolosit |
| LO-03 path join | Sanitize version `[A-Za-z0-9._-]` |
| LO-04/05 | Healthcheck fără parola în argv (`REDISCLI_AUTH`); docker-init fără echo plaintext |
| CI/CD | Pipeline: lint→tests→SAST(semgrep)→secret scan(gitleaks)→dep scan(pip-audit/npm audit)→container scan(trivy)→build→sign(cosign/sigstore) |

## Trade-offs documentate

| Mecanism | Securitate | CPU | RAM | Rețea | Complexitate |
|---|---|---|---|---|---|
| Signed jobs | Foarte mare | ~zero | ~zero | +64B/job | Medie (deploy flota) |
| Short certs | Mare | ~zero | ~zero | renew ocazional | Medie |
| HMAC events | Mare | neglijabil | ~zero | +32B/msg | Medie |
| SSRF guard | Mare | DNS lookup/req | ~zero | +ms | Mică |
| Container nnp/read-only | Medie-mare | zero | zero | zero | Medie (volume fixes) |
| Rate-limit XFF | Medie | zero | ~zero | zero | Mică |

## Riscuri reziduale acceptate explicit (post-P0)

1. **HI-03/HI-04** — distribuție nesemnată + plugin checksum opțional până la P1 (mitigat operațional: acces la `agent/bin` și Plugin rows e intern).
2. **HI-05** — SSRF cu pre-condition ADMIN/OPERATOR privilegiat (mitigat de RBAC reparat).
3. **ME-08** — sesiuni în Redis 60s lag (acceptabil single-tenant; fix P2 ieftin).
4. **Frontend audit** — Unknown; recomandat audit XSS/better-auth separat.
