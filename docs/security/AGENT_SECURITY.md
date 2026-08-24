# LokiLinux Agent Security Model

Status: implementat parțial conform `docs/superpowers/plans/2026-08-24-agent-security-hardening.md`. Acest document descrie modelul ACTUAL al codului.

## Trust model pe scurt

| Boundary | Autentificare | Integritate | Anti-replay | Privilegii |
|---|---|---|---|---|
| Agent → Control plane | mTLS mutual (TLS≥1.3, client cert per agent, CN=agent_id) | gRPC/TLS | n/a (stream) | agent rulează root (Faza 2: non-root + broker) |
| Control plane → Agent (jobs) | mTLS | **Ed25519 envelope semnat** (`_envelope`), payload binding obligatoriu | nonce persistent SQLite `seen_jobs`, 25h retenție | gate fail-closed la `enforce_signed_jobs=true` |
| Plugin artifacts | download URL controlat de server | sha256 **+** Ed25519 peste `"sha256:<hex>"` | n/a | enforcement mode = semnătura obligatorie |
| Update artifacts | platform URL | Ed25519 `.sig` verificat în installer înainte de extract | anti-downgrade (comparare versiuni în loki update) | refuz hard la verificare eșuată |

## Signed jobs — cum funcționează

1. Backend `services/job_envelope.py` decide per (job, agent) dacă atașează envelope: doar joburi privilegiate, doar agenți ≥ `MIN_AGENT_VERSION_SIGNED_JOBS` (0.37.0), doar când există cheia.
2. `services/job_signing.py` semnează forma canonică (JSON compact, chei sortate, fără `signature`) cu cheia din `JOB_SIGNING_KEY_PATH` — cheia NU pleacă niciodată de pe control plane.
3. Agentul (`internal/security/envelope.go` + `agent/job_validation.go`) verifică: structură → fereastră de valabilitate (skew 30s) → identitate (`envelope.agent_id == cfg.identity.agent_id`) → semnătură Ed25519 → replay (nonce nou) → acoperire capabilități → policy local → **payload binding** (parametrii executați == payload-ul semnat).
4. Respingere = `JobResult{ExitCode:126}` cu cod `[reason]` raportat server-side; jobul nu rămâne RUNNING.
5. Flag-uri: `security.enforce_signed_jobs` (config agent, root-owned). OFF = observability (WARN per job privilegiat nesemnat). ON fără cheie validă = agentul NU pornește.

## Capability registry & risk tiers

Mirror strict backend (`job_envelope._CAPABILITY_REGISTRY`) ↔ agent (`security/capabilities.go`). Tier-uri: LOW/MEDIUM trec fără policy local; HIGH/CRITICAL cer policy fresh (<24h) cu capabilitatea enabled. `require_approval` respinge până când există fluxul de approval claims (extensie viitoare documentată).

## Policy distribution

Canalul existent `AgentHeartbeatResponse.UpdatePolicy` (PolicyConfig) este acum consumat de agent: `policies` map name→valoare devine `capabilities`; ultima politică bună persistă în SQLite (`agent_config/security.local_policy`) și supraviețuiește restarturilor; un push malformat păstrează politica anterioară.

## Privilege bridge (gap explicit, Faza 2)

Joburile host-mutating se execută prin unități systemd tranziente spawn-uite de PID1, care moștenesc userul serviciului (astăzi root). Un agent core non-root ar avea nevoie de un bridge (polkit larg = mai rău; setuid/broker dedicat = Faza 2 `loki-agent-exec`). Până atunci:
- conținarea e asigurată de sandbox profiles per-capabilitate (MemoryMax/TasksMax/CPUQuota/NoNewPrivileges/ProtectHome) — vezi `systemd_run.go`;
- userul `loki-agent` e deja provisionat de instalatoare pentru adoptare fără reinstalare;
- gate-ul de privilegii rămâne pipeline-ul de validare din interiorul agentului.

## Ce NU poate garanta modelul (reziduuri)

- **T1 (root pe host compromis):** nimic local nu poate împiedica un atacator root să citească chei/cert agent sau să omoare procesul. Obiectivul e limitarea mișcării laterale: agentul nu deține SSH keys globale, credențiale cloud sau tokens partajați.
- **T2 (control plane compromis):** semnătura mută problema la cheia de signing. Reziduu acceptat: cheia stă pe același host (proces separat, fișier 0600); KMS/HSM prin interfața `JobSigner` = pasul următor. Policy gates locale sunt al doilea factor pentru capabilități HIGH+.

## Logging & secrets

Redacție automată (`internal/logredact`) pe chei sensibile (token/password/secret/private_key/authorization/api_key/auth/credential/bearer/cookie/passwd/privkey). Cheia publică de signing e publică by design (`GET /agent/signing-key`).
