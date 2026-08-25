# Security Hardening Completion + lokilinux-kms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Finalizează hardening-ul agentului (P11 revocare, CA rotation, enforcement complet, broker non-root, approval claims) și implementează `lokilinux/kms` ca abstracție de signing cu lifecycle chei — `JobSigner` rămâne fața stabilă, fișierul actual devine un provider interschimbabil.

**Architecture:** Provider Protocol în Python (`SigningProvider`: sign_digest/public_key), `KeyManager` cu stări ACTIVE→VERIFY_ONLY→RETIRED pe layout `keys/<key-id>/v<N>.key` + `metadata.json`. Broker Go root pe Unix socket cu SO_PEERCRED + allowlist operații care reutilizează SandboxProfiles din agent module. Revocarea = SET Redis consultat o dată per conexiune mTLS (fail-closed). Approval claims = envelope-uri Ed25519 legate de job_hash/target/caps/expiry/nonce.

**Decizii confirmate:** tot codul acum · broker surface complet cu `bash.exec` · prometheus_client · live distro tests = scripts + NOT TESTED declarat.

**Invariante:** zero breaking changes (envelope fără `key_version`=v1; agenți existenți neatinși; fără fallback silențios KMS→file sau broker→local).

---

## Faza A — P11 Certificate revocation

### Task A1: RedisCache set operations
**Files:** Modify `backend/lokilinux/cache.py`
- [ ] `sadd(key, member) -> int`, `srem(key, member) -> int`, `sismember(key, member) -> bool`, `smembers(key) -> set`
- [ ] Test: fakesync unit (cache metodele sunt thin wrappers — verific apeluri redis-py corecte prin mock)
- Commit: `feat(security): redis set operations on cache wrapper`

### Task A2: services/cert_revocation.py
**Files:** Create `backend/lokilinux/services/cert_revocation.py`, `tests/unit/test_cert_revocation.py`
```python
REVOKED_KEY = "lokilinux:certs:revoked"

class RevocationUnavailable(Exception)   # Redis down & fail_closed=True
class CertificateRevoked(Exception)

async def revoke(cache, serial: str) -> None          # sadd + audit caller-side
async def unrevoke(cache, serial: str) -> None        # srem
async def list_revoked(cache) -> list[str]            # smembers sorted
async def assert_not_revoked(cache, serial: str, *, enabled: bool = True,
                             fail_closed: bool = True) -> None:
    # disabled  -> no-op (compat mode)
    # SADD hit  -> raise CertificateRevoked
    # redis err -> raise RevocationUnavailable if fail_closed else log+pass
```
- Serial normalizat hex lowercase; input validated `^[0-9a-f]{1,40}$`
- Tests: revoked rejected / unknown accepted / redis-down fail-closed raises / redis-down permissive logs / invalid serial rejected

### Task A3: Wire la punctele de autentificare mTLS
**Files:** Modify `api/grpc/agent_service.py`, `routers/agent_install.py`
- Helper `_client_serial(context) -> str|None`: `auth_context()['x509_pem_cert']` → `load_pem_x509_certificate(...).serial_number` → hex; parse O DATĂ per stream/conexiune
- `HeartbeatStream`: după identity binding (CN==agent_id) → `assert_not_revoked` cu settings-driven `enabled`/`fail_closed`; `CertificateRevoked` → abort PERMISSION_DENIED; `RevocationUnavailable` → abort UNAVAILABLE
- `/agents/register` (cert issuance endpoint) + `/agent/download*` rămân fără lookup (nu sunt conexiuni cert-authenticated) — documentat
- Config: `certificate_revocation_enabled: bool = True`, `certificate_revocation_fail_closed: bool = True` în Settings
- Commit: `feat(security): CRL-lite certificate revocation at mTLS auth points`

### Task A4: Admin API + audit
**Files:** Modify `routers/admin.py`
- `POST /admin/certificates/{serial}/revoke` / `.../unrevoke` (require_role ADMIN), `GET /admin/certificates/revoked` (serialuri full doar ADMIN; răspunsurile non-admin nu există — endpoint e admin-only by design)
- Audit: `certificate.revoked` / `certificate.unrevoked` via AuditService cu actor
- Agents cannot reach these (JWT role gate); documentat
- Commit: `feat(security): admin certificate revocation API with audit`

## Faza B — CA rotation

### Task B1: CA bundle support
- `init-certificates.sh`: `--ca-bundle` generează `ca-new.*` idempotent + `ca-bundle.crt` (old+new concatenat)
- `grpc_server.py`: deja acceptă bytes multi-PEM (grpc native) — verify + docstring
- Installer tmpl scrie bundle-ul la agenți (`ca_path` → bundle)
- Commit: `feat(security): dual-trust CA bundle for rotation`

### Task B2: Runbook + script
- `scripts/security/rotate-ca.sh` (pași 1–9 din spec: generate→distribute→dual→rotate certs→reconnect→fleet check→revoke old→retire old→rollback guards)
- `docs/security/CERTIFICATE_ROTATION.md`
- Commit: `docs(security): CA rotation runbook without agent reinstall`

## Faza C — Enforcement completion + metrics

### Task C1: prometheus_client foundation
- Dep în pyproject `prometheus-client==0.21.x`; `lokilinux/metrics.py` contoare: unsigned_privileged_jobs_total, signed_jobs_total, invalid_signature_total, expired_signature_total, unknown_signer_total, replayed_job_total, revoked_agent_total, kms_sign_success/failure_total, kms_provider_latency (Histogram), kms_rotation_total, approval_pending/rejected_total, exec_broker_requests/denied_total, certificate_rejected_total
- Lifespan: `start_http_server(9090)` când `METRICS_ENABLED=true` (default true; port din env)
- Commit: `feat(metrics): prometheus counters + /metrics on 9090`

### Task C2: Wire counters
- Server: parse `[code]` din job_results.error respinse de agent → invalid_signature/replayed/etc.; dispatch-side unsigned counter la version-gate skip
- Agent-side counts sosesc prin rezultate — fără schimbări de protocol
- Commit: `feat(metrics): security counters wired to pipeline outcomes`

### Task C3: Anti-downgrade server-side
- `job_envelope._get_signer`: dacă enforce ON (settings) și signer indisponibil → RAISE la startup/lifespan, nu trimite nesemnat niciodată
- Commit: `feat(security): fail-closed signing when enforcement requested`

## Faza D — Approval claims criptografice

### Task D1: Claim struct + service
**Create:** `services/approval_claims.py`
```python
CLAIM_FIELDS = ["approval_id","job_id","job_hash","target_agent_id",
                "capabilities","approver_id","issued_at","expires_at",
                "nonce","key_version","signature"]
# canonical form identică cu job_signing; signature peste claim fără signature
create_claim(signer, job, approver_id, ttl=300) -> dict   # job_hash=sha256(canonical params)
verify_claim(pub_by_version, claim, job, target_agent_id, now) -> None | raises
```
- Binding checks: job_id match, job_hash match, target match, caps subset, expiry, nonce replay (prefix `claim:` în seen_jobs agent-side)
- Commit: `feat(security): approval claim creation and verification`

### Task D2: DB model + migrație
- `models/approval.py` tabelă `approval_claims(id, job_id FK, approver_id, claim_json, created_at, expires_at, consumed_at)`
- Alembic revision nouă (head curent +1)
- Commit: `feat(security): approval claims persistence`

### Task D3: approve_job integration
- `JobService.approve_job` extins: după aprobare DB → semnează claim → salvează JSON → returnat în JobResponse.approval_claim
- Commit: `feat(security): signed approval claims issued on approve`

### Task D4: Agent verification
- Envelope câștigă `approval_claim` opțional (nested, semnat separat de platform key)
- `security/policy.go`: `EvaluateAuthorizations` primește `claim *ApprovalClaim` validată; `require_approval:true` + claim valid → PASS; altfel reject (comportament actual)
- `security/approval_claim.go`: struct + Verify (mirror canonical) + replay prefix `claim:`
- Cross-language fixture nou Python→Go pentru claim
- Commit: `feat(agent): approval claim verification in local policy gate`

## Faza E — loki-agent-exec broker

### Task E1: Daemon skeleton + socket + peercred
**Create:** `agent/cmd/exec-broker/main.go`, `agent/internal/broker/`(server.go, protocol.go, operations.go)
- Socket `/run/lokilinux/exec.sock` (0770 root:loki-agent, unlink stale la start)
- SO_PEERCRED per conn: uid ∈ {loki-agent uid} obligatoriu (flag `-allowed-uid`), altfel close+audit
- NDJSON: req `{request_id, operation, arguments, job_id}` (DisallowUnknownFields) → resp `{request_id, ok, exit_code, stdout, stderr, error}`; output cap 4MB/stream; timeout per request (default 3600s, cap 4h)
- Commit: `feat(agent): exec broker daemon with peercred unix socket`

### Task E2: Operation allowlist
- `package.update{names[]}`, `service.control{name, action∈start|stop|restart|status}`, `file.manage{action∈write|chmod|chown|rm|copy, path, mode?, owner?, source?}`, `reboot{}`, `ansible.run{playbook_content≤1MB, extra_vars, roles, timeout_sec}`, `python.exec{script≤256KB, timeout_sec}`, `bash.exec{command, timeout_sec}`
- Toate prin `modules.RunUnit` exportat (wrapper peste systemd-run cu SandboxProfile: HostMutation pt primele patru, ArbitraryCode pt ansible/python/bash)
- Absolute paths only, fixed argv builders (reuse packageUpdateArgv etc. — exportate), env fix (PATH=/usr/sbin:/usr/bin:/sbin:/bin, LANG=C.UTF-8, HOME=/root)
- Per-op concurrency semaphore (max 2), audit log line per request (operation, job_id, uid, exit_code, duration) — fără conținut payload
- Commit: `feat(agent): broker allowlisted privileged operations`

### Task E3: Agent client + config
- `internal/brokerclient/client.go`: dial socket, request/response, timeout; config `security.exec_broker.socket` (gol = dezactivat → traseul local actual)
- Manager: dacă configurat, executorii privilegiați trimit prin broker; broker unreachable → JobResult error (fără fallback local)
- Unit tests cu fake socket server (schema validation, deny wrong uid simulat prin handshake field)
- Commit: `feat(agent): broker client integration behind explicit config`

### Task E4: Packaging + units + installer flip
- nfpm: `/usr/bin/loki-agent-exec` 0755; `tmpfiles.d/lokilinux.conf` (/run/lokilinux 0750 root:loki-agent)
- `lokilinux-agent-exec.service`: root, `RestrictAddressFamilies=AF_UNIX`, `IPAddressDeny=any`, ProtectSystem=strict+ReadWritePaths=/run/lokilinux /var/lib/lokilinux, NoNewPrivileges=false (necesită spawn root units — documentat), TasksMax=32
- Instalatoare: pornesc broker unit; când brokerul e activ → main unit `User=loki-agent` (+ ReadWritePaths adjust), altfel rămâne root (compat mode, WARN)
- postinstall: user provisioning deja existent ✓
- Commit: `feat(agent): exec broker packaging + non-root flip when deployed`

## Faza F — lokilinux-kms

### Task F1: provider + keys
**Create:** `backend/lokilinux/kms/__init__.py, provider.py, keys.py, file_provider.py, errors.py`
```python
class SigningProvider(Protocol):
    def sign_digest(self, key_ref: KeyRef, digest: bytes) -> bytes: ...
    def public_key(self, key_ref: KeyRef) -> Ed25519PublicKey: ...

@dataclass KeyRef: key_id:str; version:int
class KeyState(Enum): ACTIVE VERIFY_ONLY RETIRED
class KeyManager:
    # layout: {keys_dir}/{key_id}/v{n}.key (0600) + metadata.json
    # states ACTIVE(exact una) / VERIFY_ONLY(mai multe) / RETIRED(nu se mai verifică)
    create(), activate(), rotate() -> new_version (old→VERIFY_ONLY),
    retire(version), active_ref(), ref_for_version(v), verify_allowed(v)
errors: sanitized (key_id+version only, NICIODATĂ conținut/materiale)
```
- Factory `get_provider(settings)`: "file" → FileSigningProvider; "vault"/"hsm" → NotImplementedError("provider planned; interface stable")
- Commit: `feat(kms): signing provider abstraction + key lifecycle manager`

### Task F2: JobSigner facade + key_version
- `JobSigner.__init__(provider=None, key_id="job-signing")`: fără provider → FileSigningProvider pe layout vechi compat (fallback: fișier unic JOB_SIGNING_KEY_PATH = v1 implicit)
- `sign()` adaugă `"key_version": active_version` în envelope; `public_key_b64(version=None)` → activă
- Agent: `Envelope.KeyVersion *int json:"key_version,omitempty"`; Verifier primește pubkeys map versiune→cheie (config `security.signing_pub_keys` map + legacy scalar path=v1); absent → v1
- **Fixture-ul cross-language existent trebuie să rămână verde** (v1 implicit)
- Commit: `feat(kms): JobSigner over providers, versioned envelopes`

### Task F3: Rotation + admin + audit
- `POST /admin/kms/keys/{key_id}/rotate` (ADMIN) → KeyManager.rotate + audit `kms.key.rotated`(key_id, from,to — fără material)
- Audit `kms.sign.failure` sanitizat; metrics kms_* populate
- Tests: sign cu v2 activ → verify cu pubkey v2; envelope v1 încă verifiable după rotație; sign cu RETIRED → fail closed; metadata coruptă → eroare clară
- Commit: `feat(kms): key rotation admin flow with historical verification`

## Faza G — Production profile
- Settings: `security_profile: development|production`; validare lifespan: production ⇒ enforce_signed_jobs=true, revocation enabled+fail-closed, (kms.provider≠file SAU allow_file_keys_in_production=true)
- `.env.example` + docs profile block
- Commit: `feat(security): production profile startup validation`

## Faza H — Tests/scripts/docs finale
- `tests/unit/test_kms_*.py`, `test_approval_claims.py`, broker Go tests (`cmd/exec-broker` schema/authz/op matrix)
- `scripts/security/e2e_signed_job.sh` — enroll→mTLS→signed job→verify→approve→execute→audit (rulează dacă stack-ul local e up; altfel marcat SKIP)
- `scripts/security/distro-live-test.sh` + `docs/security/DISTRO_RUNBOOK.md` (systemd-analyze security + checklist per directivă) → **NOT TESTED**
- Docs: `docs/security/KMS.md`, update AGENT_SECURITY/THREAT_MODEL/EXECUTION_MODEL/ARCHITECTURE pointers
- Final review §30 checklist în plan file + raport IMPLEMENTED/TESTED/NOT TESTED/LIMITATIONS/RISKS/FOLLOW-UP
- Commits: `test(security): ...`, `docs(security): ...`

## Definition of Done mapping
P11✓A | revocation tested✓A5 | CA rotation runbook✓B (live NOT TESTED) | enforcement✓C | non-root✓E6 (cu broker deploy-at) | bridge removed✓E | broker isolated✓E1/E4 | socket protected✓E1 | peercred✓E1 | strict schema✓E2 | no shell arbitrar✓(bash.exec e operație dedicată, nu shell generic) | claims✓D | replay✓D/A | KMS abstraction✓F1 | file provider✓F2 | extensibil vault/hsm✓F1 factory | rotation✓F3 | old signatures verifiable✓F3 | secrets out of logs✓(sanitized errors+redaction existentă) | fail-closed✓A2/C3/F3/G | metrics✓C | audit✓A4/F3 | distro live✗ NOT TESTED | E2E⚠ conditional | docs✓H

## Ordine execuție
A1→A5 · B1→B2 · C1→C3 · D1→D5 · E1→E6 · F1→F3 · G · H. Commit atomic per task-grup, reviewable.
