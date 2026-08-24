# LokiLinux Agent — Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compromiterea unui Agent să nu conducă automat la compromiterea infrastructurii — Assume Breach + Zero Trust + Least Privilege + Defense in Depth, păstrând Bash/Ansible/Python și agentul lightweight.

**Architecture:** Agent core non-root (`loki-agent`), joburi privilegiate semnate Ed25519 (agent deține doar public key), capability-based authorization cu policy enforcement local pe canalul `UpdatePolicy` existent, replay protection persistentă în SQLite, sandbox per-job prin directive systemd pe unit-urile tranzinte existente (`systemd-run`). Separarea în binar dedicat `loki-agent-exec` = fază 2 opțională, doar dacă varianta systemd-first nu satisface.

**Tech Stack:** Go stdlib (crypto/ed25519), SQLite (replay store), gRPC JSON codec (wire-ul actual — NU protobuf binar), systemd transient units, nfpm packaging.

---

## Decizii (baked-in, din analiza planului original)

1. **Privilege separation:** variantă **systemd-first** — agent core non-root, privilegiile curg prin unit-uri tranzinte `systemd-run` cu directive per-capabilitate. Același trust boundary ca broker-ul separat, zero IPC custom nou (= zero suprafață nouă de privesc local). Broker-ul `loki-agent-exec` rămâne Faza 2 opțională.
2. **Signing key:** proces dedicat pe control plane din start (`job_signing.py`, cheie în fișier root-only `0600`), interfață `Signer` care permite KMS/HSM ulterior fără schimbări în agenți. Cheia NU stă niciodată pe agent.
3. **Phase 0 verificat deja** (build-mode): mTLS mutual confirmat (`grpc_server.py:76 require_client_auth=True`); wire = **JSON codec**; găsit gap nou: serverul nu leagă CN cert ↔ agent_id payload.
4. **Compatibilitate:** serverul semnează joburi noi doar pentru agenți cu `agent_version >= prag` (același mecanism ca `MIN_AGENT_VERSION_NATIVE_MODULES`, `agent_capability.py`); flag `security.enforce_signed_jobs` permite rollback instant.

## Phase 0 — Repository Security Audit (REZULTATE)

| # | Sev | Finding | Evidență | Rezolvare |
|---|---|---|---|---|
| C1 | CRITIC | Control plane compromis → RCE root pe toți agenții (fără validare la dispatch) | `manager.go:349-402` | P2 signed jobs |
| C2 | CRITIC | Agent rulează root; joburile rulează root prin unit-uri tranzinte | `install-agent.sh:161 User=root`, `systemd_run.go` | P4 |
| C3 | HIGH | Plugin install: doar SHA-256, fără semnătură | `plugin_installer.go:33` | P8 |
| C4 | HIGH | Update artifacts neverificate criptografic | `scripts/install-agent.sh` | P9 |
| C5 | MEDIUM | Replay protection doar in-memory (`inFlight` map) | `manager.go:363-370` | P3 |
| C7 | MEDIUM | Server nu leagă identitatea mTLS (CN) de `agent_id`-ul din payload — agent autentificat poate spoofa alt agent | `api/grpc/agent_service.py` | P10 |
| C6 | OK | mTLS mutual funcțional, TLS≥1.3 | `grpc_server.py:76`, `grpc_client.go:88-91` | — |
| — | INFO | Ansible executor e local-only, fără SSH keys pe agent | `ansible_executor.go:15-20` | documentare |
| — | INFO | Enrolment one-time token există (Redis TTL) | `agent_install.py:47-53` | păstrat |

Protecții existente de păstrat: argv-only execution (fără shell interpolation), output cap 4MB/stream, timeout implicit 3600s, `validateCommand`, path-traversal checks în `writeRoles`, package-name regex.

---

## P1 — Security Primitives

### Task 1.1: Pachet `internal/security` — envelope + verificare Ed25519

**Files:**
- Create: `agent/internal/security/envelope.go`
- Create: `agent/internal/security/envelope_test.go`

- [ ] **Step 1: structura envelope + canonical bytes**

```go
package security

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"sort"
	"time"
)

// Envelope is the signed job wrapper. Fields mirror the control-plane
// job_signing.py canonical form EXACTLY — signature covers the canonical
// JSON of the unsigned fields (sorted keys, no whitespace), never the raw
// wire bytes (the gRPC JSON codec may reformat).
type Envelope struct {
	JobID                 string            `json:"job_id"`
	AgentID               string            `json:"agent_id"`
	TenantID              string            `json:"tenant_id"`
	JobType               string            `json:"job_type"`
	Payload               json.RawMessage   `json:"payload"`
	PolicyID              string            `json:"policy_id,omitempty"`
	IssuedAt              int64             `json:"issued_at"`  // unix sec
	ExpiresAt             int64             `json:"expires_at"` // unix sec
	Nonce                 string            `json:"nonce"`
	RiskLevel             string            `json:"risk_level"` // LOW|MEDIUM|HIGH|CRITICAL
	RequestedCapabilities []string          `json:"requested_capabilities"`
	Signature             string            `json:"signature"` // base64(ed25519)
}

// UnsignedBytes returns the canonical serialization that signatures cover:
// the envelope without Signature, keys sorted, compact JSON.
func (e *Envelope) UnsignedBytes() ([]byte, error) {
	cp := *e
	cp.Signature = ""
	b, err := json.Marshal(cp)
	if err != nil {
		return nil, err
	}
	return canonicalJSON(b)
}

// canonicalJSON re-encodes compact JSON with object keys sorted recursively.
func canonicalJSON(in []byte) ([]byte, error) {
	var v interface{}
	dec := json.NewDecoder(bytes.NewReader(in))
	dec.UseNumber()
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return json.Marshal(sortKeys(v))
}

func sortKeys(v interface{}) interface{} {
	switch t := v.(type) {
	case map[string]interface{}:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		out := make(map[string]interface{}, len(t))
		for _, k := range keys {
			out[k] = sortKeys(t[k])
		}
		return out // NOTE: Go maps marshal sorted by key since 1.12 — this
		           // pass exists to normalize nested payloads deterministically.
	case []interface{}:
		for i := range t {
			t[i] = sortKeys(t[i])
		}
	}
	return v
}

// Verifier holds ONLY the platform's public key. Never a private key.
type Verifier struct {
	pub ed25519.PublicKey
}

func NewVerifier(pubBase64 string) (*Verifier, error) {
	raw, err := base64.StdEncoding.DecodeString(pubBase64)
	if err != nil || len(raw) != ed25519.PublicKeySize {
		return nil, fmt.Errorf("invalid platform signing public key")
	}
	return &Verifier{pub: ed25519.PublicKey(raw)}, nil
}

// VerifyResult distinguishes rejection reasons so callers can audit them.
type RejectReason string

const (
	RejectBadSignature RejectReason = "bad_signature"
	RejectExpired      RejectReason = "expired"
	RejectNotYetValid  RejectReason = "not_yet_valid"
	RejectWrongAgent   RejectReason = "wrong_agent"
	RejectMalformed    RejectReason = "malformed"
)

// Verify checks structure, validity window and signature. Clock skew
// tolerance of 30s on issued_at guards against minor drift.
func (v *Verifier) Verify(e *Envelope, expectedAgentID string, now time.Time) (RejectReason, error) {
	if e.JobID == "" || e.JobType == "" || e.Nonce == "" ||
		e.IssuedAt == 0 || e.ExpiresAt == 0 {
		return RejectMalformed, fmt.Errorf("missing required envelope fields")
	}
	if now.Unix() > e.ExpiresAt {
		return RejectExpired, fmt.Errorf("envelope expired at %d", e.ExpiresAt)
	}
	if now.Unix()+30 < e.IssuedAt {
		return RejectNotYetValid, fmt.Errorf("issued_at in the future beyond skew")
	}
	if expectedAgentID != "" && e.AgentID != expectedAgentID {
		return RejectWrongAgent, fmt.Errorf("envelope for %s, we are %s", e.AgentID, expectedAgentID)
	}
	unsigned, err := e.UnsignedBytes()
	if err != nil {
		return RejectMalformed, err
	}
	sig, err := base64.StdEncoding.DecodeString(e.Signature)
	if err != nil || len(sig) != ed25519.SignatureSize ||
		!ed25519.Verify(v.pub, unsigned, sig) {
		return RejectBadSignature, fmt.Errorf("signature verification failed")
	}
	return "", nil
}
```

(adaugă import `"bytes"`)

- [ ] **Step 2: teste** — semnează cu cheie test în test, verifică: valid ✓, tampered payload ✗ `RejectBadSignature`, expired ✗, wrong agent ✗, malformed ✗, canonical form stabilă (chei rearanjate → tot verify ok).

Run: `cd agent && go test ./internal/security/ -race -v` → PASS

- [ ] Commit: `security: Ed25519 job envelope verification (verify-only primitives)`

### Task 1.2: Distribuție signing public key la enrollment

**Files:**
- Modify: `backend/lokilinux/api/v1/routers/agent_install.py` (endpoint `/agent/signing-key.pem`)
- Modify: `backend/lokilinux/install_agent.sh.tmpl` + `scripts/install-agent.sh` (descarcă key în `/etc/lokilinux/signing_pub.b64`, chmod 644 root-owned)
- Modify: `agent/internal/config/config.go` (`SecurityConfig{EnforceSignedJobs bool, SigningPubKeyPath string}` + defaults)

- [ ] Backend servește public key (generată o dată, stocată `/etc/lokilinux/certs/job_signing.pub` lângă CA). Endpoint autentificat (user sau enrollment token).
- [ ] Installerul îl scrie în `/etc/lokilinux/signing_pub.b64`; config agent primește calea.
- [ ] Test: enroll local pe stack dev → fișierul ajunge pe host-ul de test cu permisiuni corecte.
- [ ] Commit: `distribute Ed25519 signing public key at agent enrollment`

### Task 1.3: Log redaction layer

**Files:**
- Create: `agent/internal/logredact/redact.go` (+test)
- Modify: `cmd/agent/main.go newLogger()` — wrap handler cu ReplaceAttr care filtrează chei: password, token, secret, private_key, authorization, cookie, api_key (valoare → `[REDACTED]`)

- [ ] Test: log line cu `"token":"abc"` → output conține `[REDACTED]`.
- [ ] Audit rapid `grep -rn "slog\." agent/internal | grep -iE "token|pass|secret|key"` → nicio scurgere reală găsită = documentat.
- [ ] Commit: `log redaction middleware for agent slog output`

## P2 — Signed Jobs (omoară C1)

### Task 2.1: Control plane — signing service

**Files:**
- Create: `backend/lokilinux/services/job_signing.py`
- Create: `backend/tests/unit/test_job_signing.py`
- Modify: `docker-compose.yml` env `JOB_SIGNING_KEY_PATH=/etc/lokilinux/certs/job_signing.key` (montat din certs_dir, 0600)

```python
"""Ed25519 job signing. Private key NEVER leaves this process/host;
agents hold only the public half (served at /agent/signing-key.pem)."""
import base64, json, os, time, uuid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

class JobSigner:
    def __init__(self, key_path: str):
        with open(key_path, "rb") as f:
            self._key = Ed25519PrivateKey.from_private_bytes(f.read(32))

    def sign(self, job_id, agent_id, tenant_id, job_type, payload,
             policy_id="", ttl_seconds=300, risk="HIGH",
             capabilities=("EXEC_SHELL",)) -> dict:
        now = int(time.time())
        env = {
            "job_id": job_id, "agent_id": agent_id, "tenant_id": tenant_id,
            "job_type": job_type, "payload": payload,
            "policy_id": policy_id, "issued_at": now,
            "expires_at": now + ttl_seconds, "nonce": uuid.uuid4().hex,
            "risk_level": risk, "requested_capabilities": list(capabilities),
            "signature": "",
        }
        unsigned = json.dumps(env, sort_keys=True, separators=(",", ":")).encode()
        env["signature"] = base64.b64encode(self._key.sign(unsigned)).decode()
        return env
```

- [ ] Test: semnătura generată se verifică cu vectorul echivalent Go (cross-language test fixture: semnează un envelope fix în Python, hardcodează în `envelope_test.go`, asertă Verify==nil). **Acest cross-test e obligatoriu** — canonical JSON trebuie identic în ambele limbi.
- [ ] Commit: `control-plane Ed25519 job signing service + cross-language test vectors`

### Task 2.2: Agent-side validation pipeline + replay store

**Files:**
- Create: `agent/internal/security/replay.go` (+test)
- Modify: `agent/internal/storage/sqlite.go` (migrare tabelă)
- Modify: `agent/internal/agent/manager.go` (handleJobs: validate înainte de dispatch)

```go
// replay.go — persistent dedup. SQLite table:
// CREATE TABLE IF NOT EXISTS seen_jobs(
//   nonce TEXT PRIMARY KEY, job_id TEXT NOT NULL, seen_at INTEGER NOT NULL);
// Prune: DELETE FROM seen_jobs WHERE seen_at < ? (now - max(expires window)+grace)
// Called after every successful validation; INSERT OR IGNORE — if 0 rows
// affected => duplicate => reject with "duplicate_job".
```

- [ ] Migrare SQLite idempotentă la pornire (`ensureSchema` existent).
- [ ] `manager.handleJobs`: dacă `cfg.Security.EnforceSignedJobs` → parse envelope din parametrii jobului (`_envelope` key), `verifier.Verify()`, replay check, abia apoi `runJob`. Respins = JobResult cu Error=reason, exit 126 (audit vizibil server-side), NICIODATĂ fallback la execuție.
- [ ] Flag OFF (default în prima etapă de migrare) = comportament actual, dar log WARN "unsigned privileged job allowed (flag off)" — vizibilitate înainte de activare.
- [ ] Teste: replay respins, expirat respins, wrong-agent respins, flag-off trece cu warn.
- [ ] Commit: `agent-side signed-job validation pipeline + persistent replay store`

### Task 2.3: Activare graduală

- [ ] Serverul trimite envelope DOAR dacă `agent_version >= SECURITY_MIN_VERSION` (mecanism `agent_capability.py` extins).
- [ ] Runbook: 1) deploy backend cu signing ON+agent flag OFF (observare warn-uri), 2) rollout agent nou, 3) flip flag ON per-fleet prin config.
- [ ] Commit: `staged rollout gating for signed jobs by minimum agent version`

## P3 — Capability + Policy Enforcement Local (folosește canalul `UpdatePolicy` existent)

### Task 3.1: Capability registry

**Files:**
- Create: `agent/internal/security/capabilities.go` (+test)

Mapare job_type → capabilitate + risc:

```go
var Registry = map[string]Capability{
	"HEARTBEAT":       {Risk: "LOW"},
	"FILE_READ":       {Cap: "READ_SYSTEM", Risk: "LOW"},
	"PACKAGE_UPDATE":  {Cap: "PACKAGE_MANAGEMENT", Risk: "HIGH"},
	"SERVICE":         {Cap: "SERVICE_CONTROL", Risk: "MEDIUM"},
	"COMPLIANCE_REMEDIATE": {Cap: "SECURITY_REMEDIATION", Risk: "HIGH"},
	"ANSIBLE_PLAYBOOK":{Cap: "EXEC_ANSIBLE", Risk: "CRITICAL"},
	"WORKFLOW_STEPS":  {Cap: "EXEC_BASH", Risk: "CRITICAL"}, // poate conține command/ansible
	"PLUGIN_INSTALL":  {Cap: "PLUGIN_INSTALL", Risk: "CRITICAL"},
	"REBOOT":          {Cap: "REBOOT_HOST", Risk: "HIGH"},
}
```

(`WORKFLOW_STEPS` inspectează steps și cere unia dintre EXEC_BASH/EXEC_ANSIBLE/PACKAGE_MANAGEMENT — union.)

### Task 3.2: Policy evaluator local

**Files:**
- Create: `agent/internal/security/policy.go` (+test)
- Modify: `manager.go HandleResponse` — persistă `PolicyConfig` primit pe heartbeat în SQLite (`policies` tabel, cu `received_at`)

Reguli fail-closed:
- Capabilitate CRITICAL/HIGH fără policy local valid (< TTL 24h) → **reject** ("policy unavailable")
- Capabilitate absentă din policy → reject
- `enabled:false` → reject; `require_approval:true` → accept doar dacă envelope poartă approval claim semnat separat (extensie; inițial reject cu mesaj clar)

- [ ] Commit: `local policy evaluation over heartbeat-delivered PolicyConfig (fail-closed)`

### Task 3.3: RBAC backend — capabilități ↔ roluri

**Files:**
- Modify: `backend/lokilinux/services/workflow_engine.py` + rutele care creeaza joburi (capabilitatea cerută derivată din job_type, verificată contra rolului actorului din JWT session)

Matrice: VIEWER→doar read; OPERATOR→SERVICE_CONTROL, PACKAGE_MANAGEMENT; AUTOMATION_OPERATOR→EXEC_ANSIBLE/EXEC_BASH; SECURITY_OPERATOR→SECURITY_REMEDIATION; ADMIN→policy mgmt; SUPER_ADMIN→trust/signing config. Roluri noi adăugate la enum-ul existent din migrație nouă alembic.

## P4 — Privilege Separation (systemd-first; omoară C2)

### Task 4.1: User dedicat + layout pachet

**Files:**
- Modify: `agent/scripts/agent-postinstall.sh` (creează sistem user `loki-agent`: `useradd --system --home /var/lib/lokilinux --shell /usr/sbin/nologin loki-agent`)
- Modify: `agent/.nfpm.yaml` — binary → `/usr/bin/loki-agent` (root-owned 0755); dirs `/var/lib/lokilinux` owner `loki-agent`
- Modify: `backend/lokilinux/install_agent.sh.tmpl` + `scripts/install-agent.sh` — user create, chown state/logs, certs 0600 root:loki-agent readable

### Task 4.2: Unit principal non-root + hardening extins

```ini
[Service]
User=loki-agent
Group=loki-agent
# ... existing ProtectSystem=strict, ProtectHome, PrivateTmp, NoNewPrivileges ...
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictNamespaces=true
SystemCallArchitectures=native
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryDenyWriteExecute=true   # TESTAT individual; Go runtime compatibil, dar se rollback-uiește dacă apar probleme pe distro-uri vechi
UMask=0027
```

- [ ] **FIECARE directivă testată individual** pe Ubuntu 22.04/24.04 + Rocky 9 (target-urile reale): service pornește, heartbeat trece, telemetry colectează. Directiva care strică → comentată cu motiv documentat.
- [ ] ReadWritePaths rămâne `/var/lib/lokilinux /var/log/lokilinux`.
- [ ] Commit: `run agent core as dedicated loki-agent user, extend unit hardening`

### Task 4.3: Per-capability sandbox pe unit-urile tranzinte

**Files:**
- Modify: `agent/internal/modules/systemd_run.go` — `runSystemdRunUnit` primește `SandboxProfile`

```go
type SandboxProfile struct {
	User        string // "" = root (doar pt capability care o cere explicit)
	MemoryMax   string // ex "512M"
	TasksMax    int    // anti fork-bomb
	CPUQuota    string // ex "50%"
	NoNewPrivileges bool
	ProtectSystem  string // "strict" | "full"
	PrivateTmp     bool
	RestrictSUIDSGID bool
}
```

- LOW (read-only collectors): nu mai trec prin escape — rulează ÎN namespace-ul agentului (renunțăm la systemd-run pentru telemetrie pură unde posibil).
- PACKAGE_UPDATE/SERVICE: root, MemoryMax=1G, TasksMax=256, RuntimeMaxSec (există).
- EXEC_BASH/ANSIBLE/REMEDIATE: root (mută hostul), TasksMax=128, CPUQuota=50%, NoNewPrivileges=true, ProtectHome=read-only.
- Env allowlist: `-p Environment=` doar variabile whitelist (PATH, LANG, HOME setat explicit) — nu moștenire completă.

- [ ] Test fork-bomb: `for i in $(seq 1 10000); do sleep 0.01 & done` sub profile → oprit de TasksMax. Test memory: `python3 -c "a='x'*10**11"` → OOM kill limitat, agent sănătos.
- [ ] Commit: `per-capability systemd sandbox profiles for transient job units`

## P5-P7 — Executori (consolidare peste ce există)

- [ ] Bash: timeout existent ✓, output cap ✓; adaugă working-dir restricționat + deny `LD_PRELOAD`-style env (prin allowlist deja) + audit event per execuție (P10).
- [ ] Python: același profil ca bash; script size cap (256KB) nou.
- [ ] Ansible: playbook size cap (1MB), roles size cap, timeout obligatoriu ≤ 3600s; documentat explicit "local-only, no SSH keys on host" în AGENT_SECURITY.md. JIT credentials/Vault = notat ca extensie viitoare, NEimplementat (nu există azi niciun flux de credențiale — YAGNI).

## P8 — Plugin Signing (omoară C3)

**Files:**
- Create: `backend/lokilinux/services/plugin_signing.py` (semnează manifest+artifact la publish)
- Modify: `agent/internal/modules/plugin_installer.go` — după sha256 check: verifică `signature` (Ed25519, aceeași cheie platformă) peste `sha256:<digest>`; lipsă/invalid → reject, fail-closed
- Modify: proto/payload params: `signature` + `signed_manifest` (id/version/publisher/capabilities)

- [ ] Backward: pluginuri vechi fără semnătură → reject când flag ON (documentat în migration notes).
- [ ] Commit: `require Ed25519-signed plugin manifests and artifacts`

## P9 — Secure Update (omoară C4)

**Files:**
- Modify: `Makefile` agent-package target: generează `.sig` (Ed25519 peste sha256 artifact) pentru fiecare tar.gz/deb/rpm — folosește cheia de signing ( disponibilă pe build host )
- Modify: `backend/lokilinux/api/v1/routers/agent_install.py` `_package_available` + download endpoints: servește `.sig`
- Modify: installer tmpl + `scripts/install-agent.sh`: descarcă `.sig`, verifică cu public key ÎNAINTE de install; compară versiune curentă vs nouă → refuse downgrade (anti-downgrade)

- [ ] Commit: `signed update artifacts with anti-downgrade verification in installer`

## P10 — Identity Binding + Audit Telemetry (omoară C7 + §22)

**Files:**
- Modify: `backend/lokilinux/api/grpc/agent_service.py` — extrage CN din client cert (`context.auth_context()`), compară cu `request.agent_id`; mismatch → reject + audit log
- Modify: `manager.go` — emite structuri audit pentru fiecare execuție privilegiată (event, job_id, capability, risk, policy_id, exit_code, duration) atașate heartbeat-ului următor; backend le persistă în `audit_logs`

- [ ] Commit: `bind mTLS identity to agent_id server-side; emit structured execution audits`

## P11 — Certificate rotation & revocation

- [ ] Doc + implementare minimală: endpoint revocare (CRL-lite: serial blacklist în Redis consultat la handshake via `VerifyPeerCertificate` custom pe server) — sau decizie explicită de amânare cu justificare în THREAT_MODEL.md. Rotation flow existent (`CERT_RENEWAL_DAYS`) documentat end-to-end.

## P12 — Security Tests (per §35)

**Files:** Create: `agent/internal/security/*_test.go` (majoritatea scrise inline în fazele anterioare) + `backend/tests/security/test_job_signing_flow.py`

Matrice obligatorie (fiecare = test care eșuează dacă protecția lipsește):

| Atac | Rezultat așteptat |
|---|---|
| invalid signature | reject `bad_signature` |
| expired envelope | reject |
| modified payload post-signing | reject |
| wrong agent_id | reject |
| replayed nonce/job | reject `duplicate_job` |
| unsigned privileged job (flag ON) | reject |
| unknown capability | reject |
| policy absent/stale pentru HIGH+ | reject |
| unsigned plugin | reject |
| oversized job (>16MB) | reject la transport (limita grpc existentă) |
| fork bomb | ucis de TasksMax, agent sănătos |
| memory bomb | OOM kill al unității, agent sănătos |
| output flooding | truncat la 4MB (existent ✓, test) |

Integration: stack dev up → enroll agent → semnează job → execută → audit present; apoi fiecare caz negativ.

## P13 — Documentation

**Files:**
- Create: `docs/security/AGENT_SECURITY.md` (trust model, privilege model, execution model, signing, sandboxing, secrets)
- Create: `docs/security/THREAT_MODEL.md` (T1-T5 cu răspunsurile implementate + reziduuri explicite: T1 rămâne partial — root pe host rămâne game over local)
- Create: `docs/security/EXECUTION_MODEL.md` (capability registry, risk levels, sandbox profiles)
- Modify: `docs/ARCHITECTURE.md` §agent + `docs/modules/03-agent.md`

## Migration / Backward Compatibility

1. Backend deploy (signing ON, serving envelopes doar agenților ≥ prag) — agenți vechi neatinși.
2. Agent release nou (flag OFF default) — flota upgrade-uită normal prin fluxul existent ship-changes/release.sh.
3. Observare warn-uri "unsigned job" 1-2 săptămâni.
4. Flag ON per fleet (config file push sau ansible playbook prin... signed jobs 🙂).
5. Rollback oricând: flag OFF → comportament vechi, fără redeploy.

## Rollback Plan

- Fiecare fază = commit separat + feature flag unde afectează runtime (enforce_signed_jobs, sandbox profiles prin config).
- Systemd unit vechi păstrat ca `.bak` de installer; rollback = restore + daemon-reload.
- Schema SQLite aditivă (tabele noi) — rollback fără migrații inverse.

## Security Acceptance Criteria (din §45, verificate)

- [ ] `ps aux | grep loki-agent` → User `loki-agent` (nu root)
- [ ] Job privilegiat fără semnătură validă → respins cu audit
- [ ] Replay/expired/wrong-agent → respins
- [ ] Policy absent pentru HIGH+ → respins (fail closed)
- [ ] Plugin/update fără semnătură → respins
- [ ] Fork bomb/memory bomb → conținute de cgroup limits
- [ ] Toate testele din matricea P12 trec
- [ ] `go test ./... -race` verde; suite backend verde
- [ ] CPU/RAM overhead agent: < 5% față de baseline (măsurat heartbeat loop)
