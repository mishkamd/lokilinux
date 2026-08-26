# Execution Model — LokiLinux Agent

## Fluxul unui job privilegiat

```
Control Plane
  │ job (job_type, parameters) + _envelope semnat Ed25519
  ▼
Agent manager.handleResponse
  │
  ├─ validateAndAuthorize()          [fail-closed când enforce ON]
  │   1. envelope prezent?
  │   2. structură validă (job_id/agent_id/type/nonce/expiry)
  │   3. fereastră issued_at/expires_at (skew 30s)
  │   4. agent_id == identitate locală
  │   5. Ed25519 verify (cheia publică de la enrollment)
  │   6. replay: nonce nou în seen_jobs (SQLite, 25h)
  │   7. capabilități cerute ⊇ capabilități necesare job_type-ului
  │   8. policy local: HIGH+ ⇒ enabled + fresh (<24h)
  │   9. payload binding: canonical(params−_envelope) == canonical(payload)
  │
  └─ runJob → executor → systemd-run transient unit (+SandboxProfile)
```

## Capabilități & risc

| job_type | Capabilitate | Risc |
|---|---|---|
| HEARTBEAT / FILE_READ / LOG_READ / INVENTORY_SCAN / CVE_SCAN | READ_SYSTEM / READ_LOGS | LOW |
| SERVICE | SERVICE_CONTROL | MEDIUM |
| FILE | FILE_WRITE | MEDIUM |
| PACKAGE_UPDATE / SECURITY_PATCH | PACKAGE_MANAGEMENT | HIGH |
| COMPLIANCE_REMEDIATE / REMEDIATION | SECURITY_REMEDIATION | HIGH |
| REBOOT | REBOOT_HOST | HIGH |
| FIREWALL_CHANGE | FIREWALL_CONFIGURATION | HIGH |
| CUSTOM_COMMAND / WORKFLOW_STEPS | EXEC_BASH (+union steps) | CRITICAL |
| ANSIBLE_PLAYBOOK | EXEC_ANSIBLE | CRITICAL |
| PLUGIN_INSTALL | PLUGIN_INSTALL | CRITICAL |

WORKFLOW_STEPS extinde capabilitățile după tipurile de pași prezenți (command→EXEC_BASH, ansible→EXEC_ANSIBLE, etc.).

## Sandbox profiles (systemd transient units)

| Profil | Unde | Limite |
|---|---|---|
| `ProfileHostMutation` | package ops, service, reboot, file ops | MemoryMax=1G, TasksMax=256, CPUQuota=100%, NoNewPrivileges |
| `ProfileArbitraryCode` | bash/python/ansible | MemoryMax=512M, TasksMax=128, CPUQuota=80%, NoNewPrivileges, ProtectHome=read-only |

Proprietățile devin `-p` args pe unitatea tranzientă (`systemd_run.go`). Timeout rămâne RuntimeMaxSec (config default 3600s); output cap 4MB/stream.

## Privilege bridge — decizie documentată

Unitățile tranziente moștenesc userul serviciului agent (astăzi root). Trecerea la core non-root FĂRĂ broker ar necesita polkit deschis pe manage-units (= orice proces loki-agent ar putea spawn-ui root units, golind separarea). Decizie: broker dedicat `loki-agent-exec` (socket Unix + peer creds + schema strictă) = Faza 2; userul `loki-agent` e provisionat din instalatoare pentru adoptare fără reinstalare.


## Rollout checklist (operational)

1. **Backend deploy** — noua imagine servește cheia (`/agent/signing-key`), revocarea activă, metrics pe 9090. `JOB_SIGNING_REQUIRED` rămâne false.
2. **Provisionare cheie** — `init-certificates.sh` generează `job_signing.{key,pub,pub.pem}` în certs dir (volum, ro). Verifică `GET /agent/signing-key`.
3. **Agent release ≥0.37.0** prin fluxul standard (`bump-version` skill → `release.sh`). Agenții noi primesc envelope-uri; vechiul comportament continuă pentru restul.
4. **Observație 1–2 săptămâni** — metrics: `unsigned_privileged_jobs_total` scade spre 0 pe măsură ce flota se actualizează.
5. **Enforcement** — per agent: `security.enforce_signed_jobs: true` în config. `JOB_SIGNING_REQUIRED=true` server-side odată ce toți agenții privilegiali sunt ≥0.37.0.
6. **Non-root** (după DISTRO_RUNBOOK verde): instalezi brokerul + `AGENT_NON_ROOT=1`. COMPLIANCE_REMEDIATE și package-checks merg prin broker.
7. **Production profile** — `SECURITY_PROFILE=production` validează toate cele de mai sus la startup.

## Broker security model

- Socket `/run/lokilinux/exec.sock` 0770 root:loki-agent; SO_PEERCRED uid==loki-agent obligatoriu.
- Schema NDJSON strictă (`request_id`, `operation`, `arguments`, `job_id`) — câmpuri necunoscute respinse.
- Allowlist operații: `package.check_updates`, `package.update`, `service.control`, `file.manage`, `reboot`, `ansible.run`, `python.exec`, `bash.exec`. Fiecare = executorul existent + SandboxProfile; brokerul nu adaugă semantică de execuție.
- Limită cunoscută: SO_PEERCRED autentifică UID-ul, nu procesul — un proces compromis ca loki-agent poate vorbi cu brokerul; boundary-ul real rămâne signed-job gate-ul din agent.
