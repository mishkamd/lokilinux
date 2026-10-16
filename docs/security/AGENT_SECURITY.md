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

## Privilege bridge (construit, opt-in — nu mai e un gap Faza 2)

Bridge-ul dedicat există și rulează: `internal/broker/` + `cmd/exec-broker/`, expus ca unitatea `loki-agent-exec.service` (socket Unix, `IPAddressDeny` — vezi `DISTRO_RUNBOOK.md`). Core-ul agentului poate rula ca user non-root `loki-agent` (provisionat deja de instalatoare) și mută execuția host-mutating prin broker în loc s-o ruleze el însuși ca root — activat via `AGENT_NON_ROOT=1` la instalare sau reinstalare (`systemctl restart loki-agent-exec lokilinux-agent` după).

- conținarea e asigurată de sandbox profiles per-capabilitate (MemoryMax/TasksMax/CPUQuota/NoNewPrivileges/ProtectHome, plus allowlist de variabile de mediu — vezi `systemd_run.go`);
- gate-ul de privilegii rămâne pipeline-ul de validare din interiorul agentului, neschimbat de modul root/non-root.

**Reziduu real, nu construcție lipsă:** flip-ul `AGENT_NON_ROOT=1` pe flotă n-a fost încă validat live nicăieri — doar Rocky 9.8 (`devapp.mishka.md`) a trecut pașii 1-6 din `DISTRO_RUNBOOK.md` (instalare/verificare/sandbox-bomb), pașii 7-8 (flip-ul efectiv + re-verificare post-flip) nu s-au rulat pe niciun host din flotă. Ubuntu 22.04/24.04 și al doilea host din flotă rămân netestate complet — vezi checklist-ul din `DISTRO_RUNBOOK.md`.

## Executor hardening

Fiecare executor (Bash/Python/Ansible) rulează prin `systemd_run.go`'s `SandboxProfile`, care în plus față de conținarea de resurse (secțiunea de mai sus) aplică:
- **Env allowlist**: doar `PATH`/`LANG`/`HOME` sunt trecute explicit prin `-p Environment=` unității tranziente — mediul complet al agentului NU e moștenit, deci un payload de job nu poate citi/exploata variabile de mediu ale procesului agent.
- **Timeout ceiling**: 3600s e acum un plafon real (`clampTimeoutSeconds`), nu doar default-ul pentru `timeoutSec<=0` — niciun job nu poate cere un timeout mai mare, indiferent ce trimite control plane-ul.
- **Bash**: rulează într-un working directory dedicat (`/var/lib/lokilinux/job-workdir`), nu în cwd-ul agentului.
- **Python**: script-uri peste 256KB sunt respinse înainte de dispatch (nu trunchiate).
- **Ansible**: playbook + toate fișierele din roluri, cumulat, peste 1MB sunt respinse înainte de orice scriere pe disc. **Rulează exclusiv local** (`--connection=local`, `ansible-playbook` fără inventar la distanță) — agentul nu deține și nu folosește niciodată chei SSH.

## Ce NU poate garanta modelul (reziduuri)

- **T1 (root pe host compromis):** nimic local nu poate împiedica un atacator root să citească chei/cert agent sau să omoare procesul. Obiectivul e limitarea mișcării laterale: agentul nu deține SSH keys globale, credențiale cloud sau tokens partajați.
- **T2 (control plane compromis):** semnătura mută problema la cheia de signing. Reziduu acceptat: cheia stă pe același host (proces separat, fișier 0600); KMS/HSM prin interfața `JobSigner` = pasul următor. Policy gates locale sunt al doilea factor pentru capabilități HIGH+.

## Logging & secrets

Redacție automată (`internal/logredact`) pe chei sensibile (token/password/secret/private_key/authorization/api_key/auth/credential/bearer/cookie/passwd/privkey). Cheia publică de signing e publică by design (`GET /agent/signing-key`).
