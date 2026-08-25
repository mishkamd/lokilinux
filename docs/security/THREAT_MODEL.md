# Threat Model — LokiLinux Agent

## T1 — Agent compromis (atacator root pe host)

| Întrebare | Răspuns actual |
|---|---|
| Poate citi credențialele agentului? | Da (e root) — dar agentul nu deține decât propriul cert mTLS + cheia publică de signing. Fără SSH keys globale, fără cloud creds. |
| Poate executa joburi în flota altora? | NU: orice job trimis spre alți agenți e respins la `wrong_agent`; identitatea e legată de CN-ul certificatului server-side. |
| Poate rejuca joburi vechi? | NU: nonce persistent (`seen_jobs`), respinse cu `duplicate_job`. |
| Lateral movement? | Limitat by design: niciun secret partajat, outbound-only, fără inbound port. |

Reziduu acceptat: root local rămâne game over local. Migrarea la agent non-root + broker = Faza 2.

## T2 — Control plane compromis

| Capabilitatea atacatorului | Blocaj |
|---|---|
| Forge job privilegiat | Trebuie cheia Ed25519 (`JOB_SIGNING_KEY_PATH`, 0600, proces separat). Dacă o obține → compromis total pe capabilitățile enabled; policy gates locale cer al doilea factor pentru HIGH+. Reziduu documentat. |
| Trimite job către agenți vechi | Gated: envelope doar ≥ 0.37.0; agenții vechi primesc comportamentul anterior (observability). |
| Oprește distribuția policy | Policy stale > 24h → HIGH/CRITICAL respinse fail-closed, nu deschise. |

## T3 — Network attacker

mTLS mutual TLS≥1.3 ambele direcții; replay de job blocat independent de transport (nonce); certificate CN=agent_id; revocare = ștergerea agentului + (Faza 2) CRL-lite la handshake.

## T4 — Plugin malițios

Enforcement mode: sha256 + Ed25519 peste `"sha256:<hex>"`, semnatar = cheia platformei. Fără semnătură → respins. Observability mode (rollout): doar checksum, WARN.

## T5 — Administrator malițios

RBAC per-capabilitate (`utils/capability_rbac.py`): VIEWER read-only; OPERATOR service/package; MANAGER remediation/reboot/firewall; ADMIN execution (bash/ansible/plugins). Denial-urile sunt auditate (`job.create_denied`). Execuțiile privilegiate produc JobResult cu exit code și error — vizibile în UI/audit.
