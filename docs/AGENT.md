# LokiLinux Agent — arhitectură și protocol

Documentație a componentei **agent** (binar Go static) și a fluxului complet
agent → backend → dashboard. Pentru arhitectura generală a platformei vezi
[CLAUDE.md](../CLAUDE.md).

## 1. Ce este agentul

Binar Go static (`CGO_ENABLED=0`), unul per server monitorizat. Rulează ca
serviciu (systemd), colectează inventar de sistem/pachete la fiecare
heartbeat, execută joburi trimise de platformă, și menține un cache local
SQLite pentru operare offline până la 30 zile.

Sursă: `agent/` — `cmd/agent/main.go` (entrypoint), `internal/agent/`
(orchestrare), `internal/modules/` (colectare date + execuție joburi),
`internal/communication/` (client gRPC), `internal/storage/` (cache SQLite),
`internal/config/` (parsing `agent.yaml`).

## 2. Ciclul de viață

```
main.go
  → config.Load("/etc/lokilinux/agent.yaml")
  → agent.NewManager(cfg, logger, Version, logRingBuffer)
  → mgr.Run(ctx)   — heartbeat imediat, apoi la fiecare heartbeat.interval_sec
  → SIGTERM/SIGINT → mgr.Stop() (închide conexiunea gRPC + SQLite)
```

`Manager.Run` ([manager.go](../agent/internal/agent/manager.go)) rulează bucla
principală într-un goroutine separat de purge zilnic (șterge job-uri SQLite
expirate, retenție 30 zile).

### Backoff la eșec heartbeat

Primele 2 eșecuri consecutive: retry la intervalul normal. De la al 3-lea eșec:
backoff exponențial (`interval << (failCount-3)`), plafonat la 5 minute
(`maxHeartbeatBackoff`). Vezi `Manager.nextDelay` — acoperit de
`manager_test.go`.

## 3. Instalare & enrollment

```
1. Admin generează token enrollment (24h, single-use) din dashboard
   → POST /api/v1/agent/enrollment-token  (backend, Redis TTL 86400s)
2. curl -fsSL {platform_url}/api/v1/agent/install.sh | bash -s -- --token=<TOKEN>
   → script descarcă binarul potrivit (rpm/deb/tar.gz, arch amd64/arm64)
   → POST /api/v1/agents/register  (Authorization: Bearer <TOKEN>)
     backend: verifică tokenul în Redis, creează/actualizează rândul Agent
     (status=PENDING, hostname/os_distro/os_version/arch/kernel_version),
     generează certificat client mTLS (RSA, semnat de CA internă), invalidează
     tokenul (single-use)
   → scrie /etc/lokilinux/agent.yaml + certificatele în agent_cert_dir
   → pornește serviciul systemd
3. Primul heartbeat reușit → backend setează status=ACTIVE
```

Rute relevante: `backend/lokilinux/api/v1/routers/agent_install.py`
(`/agent/packages`, `/agent/install.sh`, `/agent/enrollment-token`,
`/agent/download`, `/agent/download-direct`, `/agents/register`).

## 4. Config (`/etc/lokilinux/agent.yaml`)

```yaml
platform:
  url: https://platform.example.com
  grpc_endpoint: platform.example.com:50051
identity:
  agent_id: <uuid generat la register>
  cert_path: /etc/lokilinux/certs/agent.crt
  key_path: /etc/lokilinux/certs/agent.key
  ca_path: /etc/lokilinux/certs/ca.crt
heartbeat:
  interval_sec: 60        # default
  timeout_sec: 30         # default
  retry_backoff_max: 600  # default (secunde)
cache:
  enabled: true
  sqlite_db: /var/lib/lokilinux/agent.db   # default
  retention_days: 30                        # default
job_execution:
  max_parallel_jobs: 2      # default
  timeout_seconds: 3600     # default
  sandbox_enabled: false
logging:
  level: info
  output: stderr
```

Valorile lipsă primesc default-uri în `config.applyDefaults` — vezi
[config.go](../agent/internal/config/config.go).

## 5. Protocolul de heartbeat (gRPC + mTLS)

- Transport: gRPC bidirecțional (`HeartbeatStream`), autentificat mTLS
  (certificat generat la enrollment). Port implicit `50051`.
- **Codec custom**: nu se folosesc mesaje protobuf generate — atât Go cât și
  Python serializează/deserializează cererile ca JSON simplu peste stream-ul
  gRPC (`agent/internal/communication/grpc_client.go` — `jsonCodec{}`;
  `backend/lokilinux/grpc_server.py` — `_from_json`/`_to_json`). Structurile
  Go din `agent/gen/lokilinux/lokilinux.pb.go` sunt scrise manual (struct +
  `json:"..."` tags), nu generate de `protoc` — `proto/lokilinux.proto`
  documentează schema dar nu e compilat direct în build.

### Payload trimis de agent (`AgentHeartbeatRequest`)

| Câmp JSON | Sursă (Go) | Note |
|---|---|---|
| `agent_id` | `cfg.Identity.AgentID` | identitatea agentului (nu PK-ul din DB) |
| `system_status` | `modules.SystemInfo` | vezi tabel mai jos |
| `packages` | `PackageManagerModule.ListPackages()` | nume+versiune+arch, per pachet |
| `packages_checksum` | SHA256 al listei complete | folosit pt a evita retrimiterea inutilă |
| `agent_version` | `main.Version` (injectat la build) | `omitempty` — lipsă dacă string gol |
| `recent_logs` | `LogRingBuffer.Lines()` (ultimele 100) | |
| `log_connections`/`log_informative`/`log_critical` | `LogRingBuffer.Counts()` | contoare pe nivel |
| `health` | `SystemInfoModule.CollectHealth()` | cpu/mem/disk % (vezi mai jos) |
| `job_results` | buffer intern `Manager.pendingResults`, drenat după fiecare heartbeat reușit | rezultatele job-urilor executate de la heartbeat-ul anterior |

`health` (`modules.Health`, câmp `AgentHealth` în proto): `memory_usage`/`disk_usage`
calculate din `SystemInfo` deja colectat (fără cost suplimentar); `cpu_usage` e o
aproximare din `/proc/loadavg` normalizat la `CPUCount` (nu delta reală din
`/proc/stat` — suficient pt semnalul "server sub sarcină", vezi comentariu
`ponytail` în `CollectHealth`).

`system_status` (`SystemInfo`):

| Câmp | Sursă |
|---|---|
| `hostname` | `os.Hostname()` |
| `fqdn` | `hostname -f`, fallback la `hostname` dacă gol/eșuează (**niciodată gol**) |
| `os_family` | hardcodat `"linux"` |
| `os_distro`, `os_version` | `/etc/os-release` (`ID`, `VERSION_ID`) |
| `kernel_version` | `/proc/version` |
| `arch` | `runtime.GOARCH` |
| `system_users` | `/etc/passwd`, UID ≥ 1000, exclude shell `nologin`/`false` |

### Ce face backend-ul cu payload-ul

`backend/lokilinux/api/grpc/agent_service.py::HeartbeatStream` extrage câmpurile
și cheamă `AgentService.update_heartbeat` (`backend/lokilinux/services/agent_service.py`):

- caută agentul după `Agent.agent_id` (string, **nu** PK-ul UUID din DB —
  rutele REST folosesc PK, heartbeat-ul folosește identitatea raportată)
- setează `last_heartbeat`, `status=ACTIVE`, `last_heartbeat_ip`
- sincronizează `hostname/fqdn/os_family/os_distro/os_version/kernel_version/arch`
  — **doar valorile truthy** (`if value:`) suprascriu coloana; un string gol
  trimis de agent nu șterge o valoare anterioară, dar nici nu o populează
- `system_users`, `agent_version`, `recent_logs` (+ contoare)
- upsert în tabela `packages` (`ON CONFLICT` pe `agent_id+name+version`) —
  nu șterge pachete care nu mai sunt raportate (comentat explicit ca limitare
  cunoscută, "ponytail" în cod)
- inserează un rând `AgentHealth` per heartbeat dacă payload-ul conține `health`
  (`is_disk_full`/`is_memory_critical` calculate la prag 90%)
- aplică `job_results` — găsește rândul `JobResult` (după `job_id`+`agent_id`,
  creat când job-ul a fost asignat) și îl actualizează cu status/exit_code/output
- dacă `packages_checksum` primit == `Agent.last_packages_checksum` stocat,
  **sare complet peste upsert-ul de pachete** (evită re-scrierea a sute de
  rânduri când inventarul nu s-a schimbat); altfel sincronizează și salvează
  noul checksum
- invalidează cache Redis (`agent:{id}:*`, `vulnerability:{id}:*`)
- **nu populează** `AgentVulnerability`/`AgentMetrics` — acestea vin dintr-un
  flux separat (worker CVE, respectiv nealimentat încă — vezi §10)

Răspunsul serverului conține `pending_jobs` (job-uri `JobResult.status=PENDING`
pentru acest agent) — agentul le execută prin `JobExecutor`, pune rezultatul în
bufferul intern `Manager.pendingResults`, și îl trimite înapoi ca `job_results`
pe **următorul** heartbeat (agentul nu are alt canal către server în afara
heartbeat-ului). Bufferul se golește doar după un heartbeat reușit — dacă
trimiterea eșuează, rezultatele rămân în coadă pentru încercarea următoare.

## 6. Cache local SQLite (`storage.Store`)

Fișier: `cache.sqlite_db` (default `/var/lib/lokilinux/agent.db`). Trei tabele:

- `jobs` — coadă locală de job-uri, retenție 30 zile (`expires_at`, purjat
  zilnic de `Manager.runPurge`)
- `packages_cache` — ultimul snapshot de pachete trimis + checksum, pentru
  operare offline
- `agent_config` — key-value store generic

Un singur writer (`db.SetMaxOpenConns(1)`) — nu se folosește WAL mode, suficient
la scara unui agent per server.

## 7. Execuție joburi

Backend trimite job-uri prin `pending_jobs` în răspunsul de heartbeat. Agentul
execută comanda din `parameters.command` prin `JobExecutor`, cu timeout din
`job_execution.timeout_seconds` (sau `timeout_seconds` explicit pe job).
Job-uri fără `command` sunt ignorate cu warning.

## 8. Build & pachete de distribuție

```bash
make agent-build          # linux/amd64 static, ldflags -X main.Version=$(VERSION)
make agent-build-arm64    # linux/arm64
make agent-package        # ambele arhitecturi + .tar.gz/.deb/.rpm (nfpm)
make agent-test           # go test ./... -v -race -cover
```

`Version` e injectat exclusiv prin `-ldflags "-X main.Version=..."`; fără el,
binarul rulează cu `Version = "dev"` (default hardcodat în `main.go`) — deci
`agent_version` nu ajunge niciodată string gol dintr-un build oficial.

Pachetele RPM produse de `nfpm` au sufix de release `-1` în numele fișierului
(`lokilinux-agent-{version}-1.{arch}.rpm`) — DEB și TAR.GZ nu au acest sufix.
Vezi `frontend/utils/agentPackages.ts` / testul `agentPackages.test.ts` pentru
regula exactă de generare a numelor.

## 9. Troubleshooting: FQDN / Agent Version afișate goale în dashboard

Simptom: în tab-ul Overview al unui server, câmpurile **FQDN** și **Agent
Version** apar `—` deși `Last Seen` e recent (heartbeat-uri sosesc).

Verificat end-to-end (proto → Go → codec JSON → handler gRPC → service →
model → schema → frontend) — lanțul de cod e corect: `fqdn()` are fallback la
hostname (nu e niciodată gol), iar `Version` implicit e `"dev"` (nu string gol)
dacă binarul a fost compilat fără ldflags.

**Cauza reală**: agentul de pe acel host rulează un **binar mai vechi**,
compilat înainte ca `agent_version`/`system_status.fqdn` să fie incluse în
payload-ul de heartbeat, sau compilat manual fără `make agent-build` (deci
fără injectarea versiunii). `omitempty` pe aceste câmpuri face ca un heartbeat
vechi să nu le trimită deloc — backend-ul nu are ce scrie, coloanele rămân
`NULL` de la `register`.

**Diagnostic**:
1. Verifică versiunea rulată pe host: `lokilinux-agent --version` sau caută
   linia de log la pornire (`"LokiLinux agent starting"` cu câmpul `version`).
2. Compară cu ultima versiune publicată (`GET /api/v1/agent/packages` →
   câmpul `version`).
3. Fix: reinstalează agentul cu pachetul curent (`make agent-package` +
   redistribuire), sau reenrollment complet dacă certificatul e și el vechi.

Notă separată: dacă `--version` arată corect dar `last_heartbeat` avansează în
DB fără linii `"heartbeat sent"` corespunzătoare în jurnalul agentului (sau
invers — jurnalul arată `"heartbeat failed"` repetat dar dashboard-ul pare
totuși "recent"), verifică mai întâi ceasul sistemului și dacă rulează un
singur proces (`systemctl status lokilinux-agent`, PID unic) înainte de a
suspecta un bug de cod — log tooling-ul poate fi neconcludent în medii
containerizate/sandbox.

Testele de regresie pentru acest bug: `agent/internal/modules/system_info_test.go`
(`fqdn()` nu returnează niciodată gol) și
`agent/internal/communication/grpc_client_test.go`
(`payloadToRequest` propagă corect `agent_version`/`fqdn` când sunt furnizate),
plus `backend/tests/unit/test_agent_service.py::test_update_heartbeat_persists_fqdn_and_agent_version`.

## 10. Ce NU face (încă) agentul

- Nu raportează metrici time-series granulare (`AgentMetrics` — hypertable
  TimescaleDB pentru network/procese/etc.) — doar snapshot-uri cpu/mem/disk
  via `AgentHealth` la fiecare heartbeat (§5). Upgrade la metrici complete ar
  necesita colectare suplimentară (network I/O, procese) neimplementată încă.
- (Corectare: agentul ARE un loader de plugin-uri în Go —
  `agent/internal/modules/plugin_installer.go` implementează `InstallPlugin()`
  — download + verificare checksum SHA-256 + instalare — dispatch-uit din
  job dispatcher via `job_type` în `agent/internal/agent/manager.go:272`.)
- Nu are rotație/reînnoire automată a certificatului mTLS — la expirare,
  agentul pică silențios (fără alertă vizibilă în dashboard). Necesită
  reenrollment manual.

## 11. Reziliență conexiune

`Manager.sendHeartbeat` numără eșecurile consecutive (`failCount`). La fiecare
multiplu de `reconnectAfterFailures` (3), agentul forțează o reconectare
completă (`GRPCClient.Reconnect()` — închide `ClientConn`-ul vechi, dial nou de
la zero) în loc să reîncerce la infinit aceeași conexiune moartă. Motivat de un
incident real: un agent a rămas blocat ore întregi într-o buclă de eșecuri
"EOF" după un restart al containerului `lokilinux-grpc`, până la restart
manual — grpc-go nu recuperează mereu singur un transport mort. Vezi
`TestReconnect_ClearsStaleConnectionEvenWhenDialFails` pentru test de regresie.
