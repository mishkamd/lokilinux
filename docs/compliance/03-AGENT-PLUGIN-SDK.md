<!-- generated-by: claude -->
# Agent Plugin SDK — Compliance Collectors

## 1. Two distinct "plugin" concepts — do not conflate them

The repo already has a design doc for a plugin SDK at `docs/plugin-sdk/{go,python}/` —
`BasePlugin`/`Plugin` with `Check()`/`Collect()`/`OnInstall()`/`OnUninstall()`, driven by the
existing `plugins`/`plugin_installations` tables and the `PLUGIN_INSTALL` job type
(`backend/lokilinux/services/plugin_service.py:43`). That SDK models **optional, user-installed,
third-party integrations** (the shipped example is a read-only Zabbix connector) — installed
per-agent through an explicit approval+job flow, versioned as artifacts
(`agent/internal/modules/plugin_installer.go`), and (per its own docstring) intended to run
sandboxed, which — given `CGO_ENABLED=0` makes Go's `plugin.Open()` unavailable — implies a
subprocess/exec model, not an in-process `dlopen`.

Compliance collectors are a **different lifecycle and trust model**: they read security-
sensitive system state (`/etc/shadow` permissions, sudoers, PAM, audit rules), must run on
every managed server with zero install step, and must be fast enough to execute dozens of
times per heartbeat cycle at 100k-agent scale — subprocess-per-collector overhead is not
acceptable there. They are **compiled into the agent binary**, following the same pattern the
agent already uses for `SystemInfoModule`/`PackageManagerModule`
(`agent/internal/modules/package_manager.go`) — a plain struct with a `NewX()` constructor and
a `Collect`-shaped method, no interface, no dynamic loading, wired by hand into `Manager`.

**Extensibility point, not a contradiction:** an org that wants a *custom* org-specific check
beyond the built-in domains (e.g. an internal agent config file format) can still ship it
through the existing `docs/plugin-sdk` install path — its `collect()` output just needs to
conform to the same canonical-JSON + domain-hash shape described below so it flows through the
same delta-sync and rule-evaluation pipeline. That's the one place the two systems meet.

## 2. The compiled-in collector interface

```go
// agent/internal/compliance/collector.go
package compliance

import (
	"context"
	"time"
)

// Collector is implemented by every built-in compliance domain collector.
// Unlike the third-party docs/plugin-sdk Plugin interface, these are compiled
// into the binary and registered at agent startup — no install/uninstall
// lifecycle, no sandboxing overhead, no per-agent enable/disable via a job.
type Collector interface {
	// Domain is the stable key used everywhere downstream: inventory_snapshots.domain,
	// baseline expected_state keys, rule_evaluations.domain. Never renamed once shipped.
	Domain() string

	// Collect gathers and normalizes this domain's current state into a
	// canonical (deterministically ordered, so hashing is stable) document.
	Collect(ctx context.Context) (Facts, error)

	// Interval overrides the default heartbeat-driven cadence for expensive
	// collectors (e.g. full filesystem hash walk). Zero means "every heartbeat".
	Interval() time.Duration
}

type Facts map[string]any

// Registry is a compile-time list, not a runtime-discovered one (ponytail:
// a discovery mechanism only earns its cost if collectors need to be added
// without a binary rebuild — nothing in this module needs that yet).
var Registry = []Collector{
	&KernelCollector{},
	&SSHDCollector{},
	&SysctlCollector{},
	&FirewallCollector{},
	&SELinuxCollector{},
	&UsersGroupsCollector{},
	&SudoCollector{},
	&PAMCollector{},
	&AuditdCollector{},
	&LoginDefsCollector{},
	&PasswordPolicyCollector{},
	&MountsCollector{},
	&CronCollector{},
	&SystemdServicesCollector{},
	&NetworkCollector{},
	&DNSCollector{},
	&TimeSyncCollector{},
	&KernelModulesCollector{},
	&OpenPortsCollector{},
	&ProcessesCollector{},
	&CapabilitiesCollector{},
	&CertificatesCollector{},
	&RepositoriesCollector{},
	&ContainerRuntimeCollector{},  // docker/podman/k8s presence + config
	&FileIntegrityCollector{},     // separate cadence, see §5
}
```

## 3. Execution model — not inline in the heartbeat goroutine

Today every collector runs synchronously at the top of `sendHeartbeat`
(`agent/internal/agent/manager.go:149-176`), which is fine for the cheap existing collectors
but wrong for compliance collectors like a full `/etc` file-integrity walk. Compliance
collectors run in a **separate worker pool** owned by a new `compliance.Runner`:

```go
// agent/internal/compliance/runner.go
type Runner struct {
	registry  []Collector
	lastRun   map[string]time.Time
	lastHash  map[string]string // domain -> BLAKE3, for delta-sync (04-PROTOCOL.md)
	results   chan DomainResult
}

// Tick is called once per heartbeat interval from Manager, alongside (not
// blocking) sysMod/pkgMod. It only runs collectors whose Interval() has
// elapsed, and hands the produced Facts to the hasher + result channel —
// the heartbeat goroutine drains results without waiting on Collect() itself.
func (r *Runner) Tick(ctx context.Context) { /* ... */ }
```

`buildPayload` (`agent/internal/agent/manager.go`) gains one field: `domain_hashes
map[string]string`, populated from `Runner.lastHash`, so the wire cost is O(domains) hashes
per heartbeat, not O(domains) full bodies — see [04-PROTOCOL.md](04-PROTOCOL.md) for the
delta-sync protocol this enables.

## 4. Collector list — domain, source, per-distro notes

Every domain from the brief, with where it reads from and the one thing that differs across
RHEL-family (RHEL/OL/Rocky/Alma) vs Debian-family (Debian/Ubuntu). `parseOSRelease()`
(`agent/internal/modules/system_info.go:228`) already parses `/etc/os-release` into a map but
today only extracts `ID`/`VERSION_ID`; this module adds `ID_LIKE` parsing there so collectors
can branch on family, not on a growing if/else of individual distro IDs.

| Domain | Reads | RHEL-family | Debian-family |
|---|---|---|---|
| `kernel` | `/proc/version`, `uname -r`, `/boot/grub2/grubenv` or `/etc/default/grub` | `grub2-editenv` | `/etc/default/grub` + `update-grub` state |
| `sshd` | `sshd -T` (effective config, not just the file — resolves `Include` directives) | `/etc/ssh/sshd_config.d/*.conf` | same directive, same path pattern (OpenSSH ≥ 8.4 on both) |
| `sysctl` | `sysctl -a` filtered against a known-keys allowlist (avoid huge low-value dump) | `/etc/sysctl.d/*.conf` | same |
| `firewall` | firewalld D-Bus API if present, else nftables/iptables ruleset dump | `firewalld` default | `ufw`/`nftables`, firewalld optional |
| `selinux` | `getenforce`, `/etc/selinux/config`, `semanage` booleans if available | enabled by default | usually absent — collector reports `not_applicable`, never fabricates a value |
| `users`/`groups` | `/etc/passwd`, `/etc/group`, `/etc/shadow` metadata (hashes never read/sent) | — | — |
| `sudo` | `visudo -c` + parse `/etc/sudoers` + `/etc/sudoers.d/*` | — | — |
| `pam` | `/etc/pam.d/*` stack contents | `authselect` profile name if active | `pam-auth-update` profile if active |
| `auditd` | `auditctl -l`, `/etc/audit/rules.d/*.rules` | `auditd` present by default | often not installed — `not_applicable` |
| `login.defs` | `/etc/login.defs` | — | — |
| `password_policy` | `pwquality.conf` / PAM `pam_pwquality`/`pam_cracklib` stack | `libpwquality` | `libpam-pwquality` |
| `mounts`/`fstab` | `/proc/mounts` (already collected by `SystemInfoModule`, reused) + `/etc/fstab` diff | — | — |
| `cron`/`timers` | `/etc/cron.*`, `crontab -l` per user, `systemctl list-timers` | — | — |
| `systemd_services` | `systemctl list-unit-files`, override files under `/etc/systemd/system/*.d/` | — | — |
| `network`/`dns` | `/etc/resolv.conf`, `NetworkManager` connection profiles or `/etc/network/interfaces` | NetworkManager default | `netplan`/`ifupdown` |
| `time_sync` | `chronyc tracking`/`timedatectl`, `/etc/chrony.conf` or `/etc/ntp.conf` | `chrony` default | `systemd-timesyncd` or `chrony` |
| `kernel_modules` | `lsmod` + `/etc/modprobe.d/*.conf` (loaded + blacklisted) | — | — |
| `open_ports` | reused from existing `SystemInfoModule` listening-port collector | — | — |
| `processes` | `/proc/*/stat` snapshot (name, uid, cmdline hash — not full cmdline, avoid secrets in args) | — | — |
| `capabilities` | `getcap -r /` scoped to a configurable path allowlist (full-filesystem `getcap -r /` is expensive — default scope `/usr/bin /usr/sbin /usr/local/bin`) | — | — |
| `certificates` | configurable path list (default `/etc/ssl/certs`, `/etc/pki`) — expiry, issuer, SAN | `/etc/pki/tls` layout | `/etc/ssl` layout |
| `repositories` | reused/extended from existing package manager detection | `.repo` files under `/etc/yum.repos.d/` | `/etc/apt/sources.list(.d)` |
| `container_runtime` | `docker info`/`podman info`/`kubectl version --client` if binaries present; absent = `not_applicable`, never an error | — | — |

Oracle Linux, Rocky, and Alma need no special-casing beyond `ID_LIKE` containing `rhel fedora`
— they inherit every RHEL-family branch above; no per-vendor code paths.

## 5. File Integrity as its own collector, its own cadence

`FileIntegrityCollector` is deliberately not in the main per-heartbeat rotation — it walks
`/etc` by default and hashes every file with BLAKE3 (fixed algorithm, no per-org selectable).
Its `Interval()` defaults to 15 minutes, not every 60s beat. Watch/ignore paths come from the
operator-configured `fim_scopes` scope (global default or per-agent override,
[08-DRIFT-FIM.md](08-DRIFT-FIM.md) §6), delivered as a signed `fim_config` heartbeat field and
applied before hashing so a known-noisy path never generates spurious drift — not from
`file_integrity_ignores`/`baseline_effective` as earlier drafted, which was never built. A
file over 10MB is skipped rather than hashed (no streaming hash path).

## 6. Local state — activating the unused SQLite store

`agent/internal/storage/sqlite.go` already has a complete schema (`jobs`, `packages_cache`,
`agent_config`) but today only `PurgeExpiredJobs`/`Close` are ever called — everything else is
dead code. This module is the first real user:

```sql
-- new table, added via the same CREATE TABLE IF NOT EXISTS pattern as the existing schema
CREATE TABLE IF NOT EXISTS compliance_state (
    domain       TEXT PRIMARY KEY,
    last_hash    TEXT NOT NULL,
    last_run_at  INTEGER NOT NULL,   -- Unix epoch
    facts        TEXT                -- last canonical JSON, for offline diff if control plane unreachable
);
```

This gives the agent a working memory across restarts (today, an agent restart forgets every
in-flight state) and lets `Runner` compute `domain_hashes` without a round-trip even on the
very first heartbeat after a restart if the on-disk cache is still warm. `agent_config` (also
currently unused) stores the last-applied `baseline_effective` hash so the agent can locally
detect "my baseline changed" without waiting for the next full sync.

## 7. New agent dependencies

| Package | Purpose |
|---|---|
| `lukechampine.com/blake3` | Canonical-document hashing (pure Go, no cgo — keeps `CGO_ENABLED=0` intact) |
| `github.com/klauspost/compress/zstd` | Optional compression of full-body resync payloads over gRPC |

No YAML/TOML parser needed beyond the already-vendored `gopkg.in/yaml.v3`. No third-party
`/etc` config parsers — each collector hand-parses its own format (matching the existing
`listDpkg`/`listRPM` style in `package_manager.go`), since compliance configs (sshd_config,
sysctl, sudoers) don't have a common shape a generic library would help with.

## 8. systemd hardening impact

Collectors that read `/etc/shadow`, `auditctl`, or `getcap` need capabilities the current
hardened unit doesn't grant beyond running as root (`User=root` already, per
`install_agent.sh.tmpl`). No *new* privilege is needed since the agent already runs as root,
but `ProtectSystem=strict`/`ReadWritePaths` (currently `/var/lib/lokilinux /var/log/lokilinux`
only) must stay read-only for `/etc` — collectors only ever read, never write, so no change to
`ReadWritePaths` is required for the compliance collectors themselves. (The unrelated existing
gap that `/opt/lokilinux/plugins` isn't in `ReadWritePaths` — needed for the *other* plugin
system in §1 — is out of scope here.)
