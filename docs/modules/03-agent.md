# 03 — Agent Linux (Go)

> Documentație generată din cod la commit `77c4220` (agent v0.35.3), august 2026.

## Rol

Agentul e daemonul Go instalat pe fiecare server gestionat (10K–100K+ scale). Are două sarcini mari:

1. **Colectare și raportare** — inventar de sistem (pachete, servicii, rețea) plus **24 de colectoare compliance** (hardening de securitate: sshd, PAM, firewall...); totul pleacă spre control plane printr-un heartbeat periodic gRPC mTLS.
2. **Execuție** — job-uri primite ca răspuns la heartbeat: patch management, Ansible, remedieri compliance, pași workflow, plugin-uri.

**Comunicație exclusiv outbound**: agentul dial-ează control plane-ul; nimeni nu poate conecta la agent.

## Tehnologii și versiuni

| Componentă | Valoare | Rol |
|---|---|---|
| Go | 1.24 | Runtime compilat |
| Build | `CGO_ENABLED=0`, static | Binare `linux/amd64` + `linux/arm64` |
| gRPC | keepalive 30s/10s | Singurul canal extern — transport mTLS |
| SQLite | pure Go | Cache local: job results + stări compliance |
| slog JSON | stdlib | Loguri structurate pe stderr + ring buffer pentru heartbeat |
| nfpm | — | Packaging `.tar.gz` / `.deb` / `.rpm` |

## Compoziție

```
agent/
├── cmd/agent/main.go          # Entry-point: flag-uri, config, logger+ring buffer, Manager.Run(), SIGTERM
├── internal/
│   ├── agent/
│   │   ├── manager.go         # Bucla principală de orchestrare (539 linii)
│   │   └── logbuffer.go       # Ring buffer 100 linii loguri proprii → recent_logs în heartbeat
│   ├── communication/
│   │   ├── grpc_client.go     # Client gRPC mTLS, codec JSON sub nume „proto", reconect lazy
│   │   └── heartbeat_manager.go # Buclă heartbeat tipizată — standalone încă
│   ├── compliance/            # 24 colectoare compile-time + runner (secțiune dedicată mai jos)
│   │   ├── collector.go       # Interfața Collector + Registry + BuildRegistry
│   │   ├── runner.go          # Tick per colector, hash-uri, persistență, LoadState
│   │   ├── canonical.go       # Normalize() + CanonicalJSON() + Hash() — facts hash-uibile determinist
│   │   └── *_collector.go     # Câte un fișier per domeniu (+ teste)
│   ├── config/
│   │   └── config.go          # /etc/lokilinux/agent.yaml — structuri + defaults
│   ├── modules/               # Executorii și colectoarele de inventar (vezi tabel)
│   └── storage/
│       └── sqlite.go          # Cache persistent: job results neconfirmate + compliance_state + purge zilnic
├── gen/lokilinux/             # Cod generat din proto/*.proto (make proto)
└── .nfpm.yaml                 # Config pachete .deb/.rpm
```

### Module interne (`internal/modules/`)

| Fișier | Rol |
|---|---|
| `system_info.go` | Inventar: hostname, OS, kernel, CPU/RAM, discuri, interfețe rețea, block devices (`lsblk`), porturi în ascultare (`ss -tulpn`), utilizatori UID≥1000; colectează și `Health` (CPU/RAM/disk/swap usage) |
| `package_manager.go` | Listare pachete apt/dnf/yum/zypper + checksum SHA-256 pentru delta-sync; scanare vulnerabilități vs versiuni fixe |
| `package_updater.go` | Execuție `PACKAGE_UPDATE` — upgrade pachete |
| `vulnerability.go` | Tip `Vulnerability` pentru heartbeat |
| `metrics.go` | Stream `ReportMetrics` |
| `job_executor.go` | Rulare comandă shell generică cu timeout |
| `ansible_executor.go` | Rulare playbook Ansible ad-hoc (conținut + extra_vars + roles materializate) |
| `python_executor.go` | Executor Python (folosit de remediation) |
| `remediation_executor.go` | `COMPLIANCE_REMEDIATE`: lanț acțiuni secvențiale (provider + body randat), mod DRY_RUN |
| `workflow_steps_executor.go` | `WORKFLOW_STEPS`: execută lista coalescată de pași workflow |
| `plugin_installer.go` | `PLUGIN_INSTALL`: descărcare + verificare checksum SHA-256 + instalare în `/opt/lokilinux/plugins/` |
| `reboot.go`, `service.go`, `file.go` | Job-uri native REBOOT / SERVICE / FILE |
| `systemd_run.go` | Suport systemd |

## Subsistemul compliance (`internal/compliance/`)

### Model

Fiecare domeniu e un `Collector` (`collector.go:21-32`) cu trei metode:

```go
Domain() string                    // cheie stabilă — niciodată redenumită după ship
Collect(ctx) (Facts, error)        // Facts = map[string]any normalizat
Interval() time.Duration           // 0 = la fiecare heartbeat; >0 = cadență proprie
```

Registry-ul e **compilat în binar** (`collector.go:42-67`), deliberat separat de plugin SDK-ul terț sandboxed: acestea citesc stări de securitate sensibile pe fiecare host, la o cadență pentru care modelul sandboxed nu e construit.

### Cele 24 de colectoare

| Domeniu | Ce colectează |
|---|---|
| `sshd` | Configurație sshd_config efectivă |
| `sysctl` | Parametri kernel sysctl |
| `users` | Conturi locale + atribute |
| `mounts` | Mount-uri active + opțiuni |
| `sudo` | Configurație sudoers |
| `pam` | Stive PAM per serviciu |
| `auditd` | Reguli audit active |
| `firewall` | Reguli iptables/nftables/firewalld |
| `selinux` | Stare SELinux/AppArmor |
| `kernel` | Versiune kernel + parametri boot |
| `login_defs` | `/etc/login.defs` |
| `password_policy` | Politica parolelor |
| `cron` | Job-uri cron programate |
| `systemd_services` | Unit-uri systemd (enabled/disabled + stare) |
| `network` | Interfețe + configurare IP |
| `time_sync` | NTP/timesyncd configurat |
| `kernel_modules` | Module kernel încărcate/blocate |
| `open_ports` | Socketuri în LISTEN |
| `processes` | Procese rulante relevante |
| `capabilities` | Capabilities Linux pe binare |
| `certificates` | Certificate TLS instalate (expirabile) |
| `repositories` | Repo-uri APT/DNF activate |
| `container_runtime` | Docker/containerd prezent + versiune |
| `file_integrity` | Hash-uri fișiere watch (configurabil din YAML) |

Singurul colector configurabil per deployment: `file_integrity` — `BuildRegistry(watchPaths, ignores)` (`collector.go:74-83`) înlocuiește lista compilată implicită cu cea din config. Restul sunt identici peste tot.

### Runner-ul (`runner.go`)

Rulează în **goroutine separată** de bucla heartbeat (tick bază 60s, pornit din `manager.go:139`) tocmai ca un colector scump (ex. walk-ul `/etc` pentru file integrity) să nu întârzieze vreun heartbeat:

1. La fiecare tick, per colector: dacă `Interval()` nu s-a scurs de la ultima rulare → skip.
2. `Collect()` — eroarea unui colector **nu blochează** celelalte (log warn + continue).
3. `Normalize(facts)` (`canonical.go`) — colapsează structurile nested în `map[string]any`; altfel hash-ul local nu ar coincide niciodată cu cel recalculat server-side după decode JSON.
4. `Hash(facts)` — SHA pe conținutul canonizat → baza delta-sync-ului.
5. Persistă `{domain, hash, facts JSON}` în tabelul SQLite `compliance_state`.

API expus către manager:
- `LoadState(ctx)` — la pornire încarcă ultimele rezultate din SQLite → după restart agentul NU retrimite full-body pe toate domeniile;
- `Hashes()` → câmpul `domain_hashes` al heartbeat-ului;
- `FullBody(domain)` → câmpul `domain_full`, când serverul a cerut `resync_domains`.

## Cum funcționează bucla principală

`Manager.Run()` (`manager.go:131`):

1. Pornește goroutine `runPurge` (purjare SQLite zilnică).
2. Încarcă starea compliance persistată (`LoadState`) și pornește `complianceRunner.Run()` în goroutine separată.
3. Trimite imediat un heartbeat, apoi intră în `select`:
   - timer expirat → heartbeat;
   - `nudge` → heartbeat anticipat (un job s-a terminat; buffered chan 1 → bursturile coalesc);
   - `stop`/ctx done → exit.
4. **Backoff exponențial** după 3+ eșecuri consecutive: interval ×2^n, plafon 5 minute; redisconectare forțată la multiplu de 3 eșecuri (grpc-go nu recuperează fiabil un transport blocat pe EOF).

### Anatomia unui heartbeat (`sendHeartbeat`, `manager.go:206`)

```
Colectare                     Payload                              Transport
─────────                     ───────                              ─────────
sysMod.Collect()         ┐    map[string]interface{}:              GRPCClient.
pkgMod.ListPackages()    ├──► agent_id, timestamp, system,        SendHeartbeat()
  + checksum SHA-256     │    packages, packages_checksum,            │
pkgMod.Vulnerabilities() │    vulnerabilities, health,                ▼
logBuf.Lines()/Counts()  │    recent_logs, log_connections,       codec JSON
health = CollectHealth() │    informative/critical,               peste gRPC
pendingResults (job-uri) │    job_results,                        „proto"
complianceRunner         ┘    domain_hashes, domain_full          (mTLS)
```

Delta-sync pe două niveluri:

- **Pachete**: checksum SHA-256 al listei — neseschimbat → serverul cere doar diff;
- **Compliance**: `domain_hashes` per domeniu — serverul compară cu starea așteptată și poate răspunde `resync_domains[]`; următorul heartbeat include apoi `domain_full` (facts complete) doar pentru domeniile cerute.

Rezultatele job-urilor (`pendingResults`) și cererile de resync se golesc **după** confirmarea trimiterii — heartbeat eșuat → rămân în coadă pentru retry.

### Procesarea răspunsului (`handleResponse`, `manager.go:332`)

Serverul poate răspunde cu:

- `resync_domains[]` → memorate până la următorul heartbeat;
- `pending_jobs[]` → fiecare job:
  - guard `inFlight` (map+mutex): același `job_id` nu poate rula dublu paralel (backstop local contra redispatch);
  - rulează **în goroutine separată** — un `PACKAGE_UPDATE` lung nu blochează bucla de heartbeat (altfel HeartbeatMonitorWorker ar marca agentul INACTIVE mid-job);
  - timeout implicit din config (3600s), suprascris per-job;
  - rezultatul intră în `pendingResults` + `nudge` către buclă.

### Dispatch job-uri după tip (`runJob`, `manager.go:422`)

| job_type | Executor |
|---|---|
| `PACKAGE_UPDATE` | `UpdatePackages` |
| `ANSIBLE_PLAYBOOK` | `AnsibleExecutor.Execute(playbook_content, extra_vars, roles)` |
| `COMPLIANCE_REMEDIATE` | `RemediationExecutor` (acțiuni provider+body, DRY_RUN opțional) |
| `WORKFLOW_STEPS` | `WorkflowStepsExecutor` (pași coalescați) |
| `REBOOT` / `SERVICE` / `FILE` | module native |
| `PLUGIN_INSTALL` | `InstallPlugin` (checksum SHA-256 obligatoriu) |
| orice alt tip | fallback: parametrul `command` rulat ca shell; fără `command` → FAILED explicit |

Notă din cod: pașii workflow de tip service/system/file/package sunt compilați momentan la shell (`CUSTOM_COMMAND`) de backend, pentru că protocolul nu are încă negociere versiune/capabilități — agenții vechi trebuie să poată primi orice job.

## Configurație (`/etc/lokilinux/agent.yaml`)

Structuri în `internal/config/config.go`, parsate cu defaults aplicate (`applyDefaults`):

| Secțiune | Chei | Default | Rol |
|---|---|---|---|
| `platform` | `url`, `grpc_endpoint` | — | Adresa control plane-ului |
| `identity` | `agent_id`, `cert_path`, `key_path`, `ca_path` | — | Identitate mTLS |
| `heartbeat` | `interval_sec`, `timeout_sec`, `retry_backoff_max` | 60 / 30 / 600 | Cadență + timeout heartbeat |
| `cache` | `enabled`, `path`, `sqlite_db`, `retention_days` | `/var/lib/lokilinux/agent.db`, 30 zile | Cache local SQLite |
| `job_execution` | `max_parallel_jobs`, `timeout_seconds`, `sandbox_enabled` | 2 / 3600 / false | Limite execuție job-uri |
| `logging` | `level`, `output` | info | Nivel loguri |
| `file_integrity` | `watch_paths`, `ignore_paths` | lista compilată implicită | Override FIM fără rebuild |

## Entry-point și ciclu de viață (`cmd/agent/main.go`)

- Flag-uri: `-config` (default `/etc/lokilinux/agent.yaml`), `-version`.
- Logger JSON pe stderr înfășurat în **ring buffer de 100 linii** (`logbuffer.go`) — ultimele N linii + contoare (conexiuni reușite / informative / critice) pleacă în fiecare heartbeat: suportul vede ce vede agentul, fără SSH pe host.
- `SIGTERM`/`SIGINT` → `cancel()` context + `mgr.Stop()` — închide clientul gRPC și SQLite.

Notă de tranziție: `communication/heartbeat_manager.go` conține o variantă complet tipizată a buclei heartbeat (pe mesajele proto generate), momentan standalone — comentariul din cod spune „wired into AgentManager in Val 3". Bucla activă azi rămâne cea din `manager.go`.

## Comunicația mTLS (`communication/grpc_client.go`)

- Codec JSON înregistrat sub numele `"proto"` (init, `grpc_client.go:23-34`) — swap documentat spre proto binar.
- Conexiune **lazy**: dial la primul RPC; keepalive 30s/10s.
- Certificat client + CA din căile configurate (`identity.cert_path/key_path/ca_path`).
- Max message 16 MB (egal cu serverul).

## Dependențe

- Control plane gRPC :50051 (mTLS) — singura comunicare externă.
- Package manager local (apt/dnf/yum/zypper), systemd, lsblk/ss, PAM/sudo/sshd configs pentru colectoare.
- `/opt/lokilinux/plugins/` — destinație plugin-uri agent-side.
- SQLite local (`/var/lib/lokilinux/agent.db`) pentru cache.

## Decizii de design

1. **Static binary, CGO off** — deploy trivial pe orice distribuție (driver SQLite pure-Go).
2. **Outbound-only** — zero porturi deschise pe hosturile gestionate; NAT traversal gratuit.
3. **Job-uri off-loop** — execuția în goroutine + guard `inFlight` previne blocarea heartbeat-ului și dispatch duplicat.
4. **Nudge channel** — rezultatul unui job ajunge la server aproape instant, nu la următorul tick programat.
5. **Delta-sync dublu** — checksum pachete + hash-uri domenii compliance: inventarul complet se trimite doar când s-a schimbat ceva.
6. **Colectoare compile-time, nu plugin-uri** — citesc stări de securitate sensibile la cadență înaltă; SDK-ul sandboxed rămâne pentru extensii terțe.
7. **Normalize înainte de hash** — facts colapseate la `map[string]any` ca hash-ul local să fie identic cu cel recalculat server-side; persistat în SQLite ca restart-ul să nu coste un resend full.



