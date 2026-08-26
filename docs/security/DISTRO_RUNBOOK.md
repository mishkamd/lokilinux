# DISTRO RUNBOOK — Live systemd Security Testing

Status: **NOT EXECUTED** (mediul de dezvoltare nu are VM-uri Ubuntu/Rocky).
Rulează manual pe fiecare distro înainte de rollout-ul non-root.

## Ținte

| Distro | systemd | Note |
|---|---|---|
| Ubuntu 22.04 | 249 | RestrictNamespaces OK, MemoryDenyWriteExecute OK cu Go |
| Ubuntu 24.04 | 255 | + SetCredentialExposes nu e folosit; comportament identic 22.04 așteptat |
| Rocky Linux 9 | 252 | SELinux activ — unit-urile rulează sub policy `init_t` implicit; SELinux dedicat = Faza viitoare |

## Procedură per distro (≈20 min)

```bash
# 1. Instalare agent (root mode, compat)
curl -fsSL https://<platform>/api/v1/agent/install.sh | bash -s -- --token=<TOKEN>

# 2. Verificări de bază
systemctl is-active lokilinux-agent lokilinux-agent-exec
systemd-analyze verify lokilinux-agent.service loki-agent-exec.service
systemd-analyze security lokilinux-agent.service --no-pager   # scorul așteptat: ≥ 8/10
systemd-analyze security loki-agent-exec.service --no-pager

# 3. Restart / upgrade / shutdown
systemctl restart lokilinux-agent loki-agent-exec
dnf/apt upgrade pachetul lokilinux-agent && systemctl restart lokilinux-agent

# 4. Rețea — broker NU trebuie să aibă IP outbound
ss -tnp | grep loki-agent-exec          # așteptat: nimic (doar socket unix)
journalctl -u loki-agent-exec | grep -i network   # IPAddressDeny hits, dacă ar fi

# 5. Filesystem — ProtectSystem=strict pe agent core
ls /usr/local/test-write 2>&1           # din unit: Read-only file system așteptat

# 6. Resource limits — sandbox profiles
# fork bomb sub bash.exec → ucis de TasksMax=128, agent sănătos:
# (trimite job WORKFLOW_STEPS cu command "for i in $(seq 1 10000); do sleep 0.01 & done")
# memory bomb sub python.exec → OOM kill al tranzientului, agent healthy

# 7. Non-root flip (după ce 1-6 trec)
AGENT_NON_ROOT=1 re-instalează sau:
  systemctl edit lokilinux-agent   # [Service] User=loki-agent
  chown -R loki-agent:loki-agent /var/lib/lokilinux /var/log/lokilinux
  systemctl restart loki-agent-exec lokilinux-agent

# 8. Post-flip: heartbeat OK, telemetry packages OK (prin broker),
#    signed privileged job executat, audit în DB.
```

## Directive de verificat individual (plan §15)

Directiva | Ubuntu 22.04 | Ubuntu 24.04 | Rocky 9
---|---|---|---
ProtectSystem=strict | ✓ | ✓ | ✓
NoNewPrivileges | ✓ | ✓ | ✓
RestrictNamespaces | ✓ | ✓ | ✓ (systemd≥239)
SystemCallArchitectures=native | ✓ | ✓ | ✓
LockPersonality / RestrictSUIDSGID | ✓ | ✓ | ✓
ProtectKernel*/ControlGroups/Clock/Hostname | ✓ | ✓ | ✓
MemoryDenyWriteExecute | **de testat** — dacă Go runtime crapă la startup, rămâne comentată (comentariul din installer explică)
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 | ✓ agent | ✓ | ⚠ verifică netlink pentru systemd-run din broker (brokerul are doar AF_UNIX)

## Criteriu de închidere

Fiecare distro: toate punctele 1–8 trec + scor systemd-analyze ≥8 + zero regresii funcționale (heartbeat, telemetry, un signed job real, un remediation dry-run). Atunci activezi `AGENT_NON_ROOT=1` flota-wide.
