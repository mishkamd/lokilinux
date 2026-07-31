package modules

import (
	"context"
	"crypto/sha256"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"sort"
	"strings"
	"sync"
	"time"
)

// updateCheckTimeoutSec bounds a single check-for-updates command (dnf/apt/
// zypper hitting real repo metadata, via the systemd-run escape hatch below
// — see its own doc comment for why a plain exec.Command from inside the
// agent's own sandbox can't do this at all).
const updateCheckTimeoutSec = 120

// Package represents a single installed system package.
type Package struct {
	Name         string
	Version      string
	Architecture string
	InstalledAt  time.Time

	// Populated from the package manager's own "check for updates" command
	// (refreshed at most once per updateCheckInterval, not every heartbeat —
	// see refreshUpdates). Zero-valued when no update is available or the
	// check hasn't run yet.
	LatestVersion    string
	UpdateAvailable  bool
	IsSecurityUpdate bool
}

// updateInfo is what checkXUpdates functions report per package name.
type updateInfo struct {
	latestVersion string
	security      bool
}

// updateCheckInterval bounds how often ListPackages actually queries repo
// metadata for available updates. Unlike listing installed packages (pure
// local state, cheap), a real check-for-updates hits the configured repos —
// doing that on every 60s heartbeat would mean 60 repo hits/hour/host, which
// doesn't scale to a fleet. Installed-package inventory (name/version/arch)
// is unaffected and still refreshes every call.
const updateCheckInterval = time.Hour

// PackageManagerModule detects the distro package manager and lists installed
// packages, plus (rate-limited) what updates are available for them.
type PackageManagerModule struct {
	mu        sync.Mutex
	lastCheck time.Time
	updates   map[string]updateInfo
}

func NewPackageManagerModule() *PackageManagerModule { return &PackageManagerModule{} }

// ListPackages returns all installed packages (with available-update info
// merged in) and a SHA256 checksum of the list. The checksum is used by the
// heartbeat to detect inventory changes without sending the full list every
// cycle — it includes LatestVersion specifically so a newly-published
// update (with the installed version unchanged) still changes the checksum
// and isn't silently skipped.
func (m *PackageManagerModule) ListPackages() ([]Package, string, error) {
	pm := detectPackageManager()

	var pkgs []Package
	var err error
	switch pm {
	case "apt":
		pkgs, err = listDpkg()
	case "dnf", "yum":
		pkgs, err = listRPM()
	case "zypper":
		pkgs, err = listRPM() // zypper also uses rpm backend
	default:
		return nil, "", fmt.Errorf("unsupported package manager: %s", pm)
	}
	if err != nil {
		return nil, "", err
	}

	updates := m.refreshUpdates(pm)
	for i := range pkgs {
		if info, ok := updates[pkgs[i].Name]; ok {
			pkgs[i].LatestVersion = info.latestVersion
			pkgs[i].UpdateAvailable = true
			pkgs[i].IsSecurityUpdate = info.security
		}
	}

	checksum := packageChecksum(pkgs)
	return pkgs, checksum, nil
}

// refreshUpdates returns the cached name->updateInfo map, refreshing it via
// the package manager's check-for-updates command only once the cache is
// older than updateCheckInterval.
func (m *PackageManagerModule) refreshUpdates(pm string) map[string]updateInfo {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.updates != nil && time.Since(m.lastCheck) < updateCheckInterval {
		return m.updates
	}

	var updates map[string]updateInfo
	var err error
	switch pm {
	case "apt":
		updates, err = checkAptUpdates()
	case "dnf", "yum":
		updates, err = checkDnfUpdates(pm)
	case "zypper":
		updates, err = checkZypperUpdates()
	default:
		updates = map[string]updateInfo{}
	}
	if err != nil {
		// Non-fatal: installed-package inventory is still useful without
		// update info (e.g. a transient network blip hitting the repo).
		// Keep serving whatever's cached rather than wiping it to empty.
		// Logged (not just swallowed) — a silent failure here previously
		// looked identical to "system fully up to date" in the DB, which
		// cost real debugging time to tell apart.
		slog.Default().Warn("package update check failed", "package_manager", pm, "error", err)
		if m.updates != nil {
			return m.updates
		}
		return map[string]updateInfo{}
	}

	m.updates = updates
	m.lastCheck = time.Now()
	return updates
}

// detectPackageManager returns "apt", "dnf", "yum", or "zypper".
func detectPackageManager() string {
	paths := map[string]string{
		"/usr/bin/apt":    "apt",
		"/usr/bin/dnf":    "dnf",
		"/usr/bin/yum":    "yum",
		"/usr/bin/zypper": "zypper",
	}
	for path, name := range paths {
		if _, err := os.Stat(path); err == nil {
			return name
		}
	}
	return "unknown"
}

// listDpkg parses `dpkg -l` output for Debian/Ubuntu systems.
func listDpkg() ([]Package, error) {
	out, err := exec.Command("dpkg", "-l").Output()
	if err != nil {
		return nil, fmt.Errorf("dpkg -l: %w", err)
	}

	var pkgs []Package
	for _, line := range strings.Split(string(out), "\n") {
		// only "ii" lines are fully installed
		if !strings.HasPrefix(line, "ii") {
			continue
		}
		// ii  name  version  arch  description
		fields := strings.Fields(line)
		if len(fields) < 4 {
			continue
		}
		pkgs = append(pkgs, Package{
			Name:         fields[1],
			Version:      fields[2],
			Architecture: fields[3],
		})
	}
	return pkgs, nil
}

// listRPM parses `rpm -qa` output for RHEL/Rocky/AlmaLinux/SUSE systems.
func listRPM() ([]Package, error) {
	// Format: name|version|arch|installtime-epoch
	out, err := exec.Command("rpm", "-qa",
		"--qf", "%{NAME}|%{VERSION}-%{RELEASE}|%{ARCH}|%{INSTALLTIME}\n",
	).Output()
	if err != nil {
		return nil, fmt.Errorf("rpm -qa: %w", err)
	}

	var pkgs []Package
	for _, line := range strings.Split(string(out), "\n") {
		parts := strings.Split(strings.TrimSpace(line), "|")
		if len(parts) < 3 || parts[0] == "" {
			continue
		}
		p := Package{
			Name:         parts[0],
			Version:      parts[1],
			Architecture: parts[2],
		}
		pkgs = append(pkgs, p)
	}
	return pkgs, nil
}

// checkDnfUpdates runs `<bin> check-update` (bin is "dnf" or "yum") and
// parses its output via parseDnfCheckUpdate.
//
// Routed through runViaSystemdRunArgv, not a plain exec.Command — confirmed
// live: dnf (any subcommand, including a read-mostly check-update) needs to
// write its own cache/log state (/var/cache/dnf, /var/log/dnf.log), which
// fails with "Read-only file system" from inside the agent's own
// ProtectSystem=strict sandbox. Same constraint that PACKAGE_UPDATE jobs
// hit (see systemd_run.go) — it isn't specific to package installation, dnf
// can't run at all here without escaping the sandbox first.
//
// check-update's exit code is significant, not incidental: 0 = no updates,
// 100 = updates ARE available (still valid stdout, not an error), anything
// else = a real failure. Treating 100 as an error would silently discard
// every result on the (common) case where updates exist.
func checkDnfUpdates(bin string) (map[string]updateInfo, error) {
	ctx, cancel := context.WithTimeout(context.Background(), updateCheckTimeoutSec*time.Second)
	defer cancel()

	result := runViaSystemdRunArgv(ctx, "pkg-check-update", []string{bin, "check-update"}, "", updateCheckTimeoutSec, 2*1024*1024)
	if result.Error != "" {
		return nil, fmt.Errorf("%s check-update: %s", bin, result.Error)
	}
	if result.ExitCode != 0 && result.ExitCode != 100 {
		return nil, fmt.Errorf("%s check-update: exit %d: %s", bin, result.ExitCode, result.Stderr)
	}
	updates := parseDnfCheckUpdate(result.Stdout)

	// Best-effort: a failed security lookup doesn't invalidate the update
	// list, the packages just won't be flagged as security updates.
	secResult := runViaSystemdRunArgv(ctx, "pkg-check-update-security", []string{bin, "updateinfo", "list", "security"}, "", updateCheckTimeoutSec, 2*1024*1024)
	if secResult.Error == "" && secResult.ExitCode == 0 {
		markSecurityUpdates(secResult.Stdout, updates)
	}

	return updates, nil
}

// parseDnfCheckUpdate parses `dnf/yum check-update` stdout: lines shaped
// "name.arch  version-release  repo", a metadata-freshness banner line, and
// (sometimes) a trailing "Obsoleting Packages" section in a different shape.
func parseDnfCheckUpdate(output string) map[string]updateInfo {
	updates := map[string]updateInfo{}
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "Last metadata") {
			continue
		}
		if strings.HasPrefix(line, "Obsoleting Packages") {
			// Different format from here on (obsoletes lines have their own
			// "new-pkg  ver  repo" + indented "  obsoletes old-pkg ver"
			// continuation) — not a package we're currently tracking updates
			// for in the same shape, so stop rather than misparse it.
			break
		}
		fields := strings.Fields(line)
		if len(fields) != 3 {
			continue
		}
		nameArch, version := fields[0], fields[1]
		name := nameArch
		if idx := strings.LastIndex(nameArch, "."); idx > 0 {
			name = nameArch[:idx]
		}
		updates[name] = updateInfo{latestVersion: version}
	}
	return updates
}

// markSecurityUpdates flags entries in updates that have a pending security
// advisory, from `<bin> updateinfo list security` output. Each line ends in
// an rpm NEVRA like "openssl-1.2.3-4.el9.x86_64" — rather than trying to
// split that back into name/version/release/arch (ambiguous: package names
// themselves routinely contain dashes, e.g. "python3-requests"), this
// matches by prefix against the already-known-clean names from
// parseDnfCheckUpdate's own parse, since a NEVRA always starts with the
// exact package name followed by "-".
func markSecurityUpdates(output string, updates map[string]updateInfo) {
	for _, line := range strings.Split(output, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 3 {
			continue
		}
		nevra := fields[len(fields)-1]
		for name, info := range updates {
			if !info.security && strings.HasPrefix(nevra, name+"-") {
				info.security = true
				updates[name] = info
			}
		}
	}
}

// checkAptUpdates runs `apt list --upgradable` and parses its output via
// parseAptUpgradable. Routed through runViaSystemdRunArgv — same reasoning
// as checkDnfUpdates: apt needs to write its own state even for a read
// query, which the agent's own sandbox blocks.
func checkAptUpdates() (map[string]updateInfo, error) {
	ctx, cancel := context.WithTimeout(context.Background(), updateCheckTimeoutSec*time.Second)
	defer cancel()

	result := runViaSystemdRunArgv(ctx, "pkg-check-update", []string{"apt", "list", "--upgradable"}, "", updateCheckTimeoutSec, 2*1024*1024)
	if result.Error != "" {
		return nil, fmt.Errorf("apt list --upgradable: %s", result.Error)
	}
	if result.ExitCode != 0 {
		return nil, fmt.Errorf("apt list --upgradable: exit %d: %s", result.ExitCode, result.Stderr)
	}
	return parseAptUpgradable(result.Stdout), nil
}

// parseAptUpgradable parses `apt list --upgradable` stdout: lines shaped
// "firefox/jammy-updates 115.0 amd64 [upgradable from: 114.0]".
func parseAptUpgradable(output string) map[string]updateInfo {
	updates := map[string]updateInfo{}
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "Listing...") {
			continue
		}
		nameRepo, rest, found := strings.Cut(line, " ")
		if !found {
			continue
		}
		name, repo, found := strings.Cut(nameRepo, "/")
		if !found {
			continue
		}
		fields := strings.Fields(rest)
		if len(fields) < 1 {
			continue
		}
		updates[name] = updateInfo{
			latestVersion: fields[0],
			security:      strings.Contains(repo, "-security"),
		}
	}
	return updates
}

// checkZypperUpdates runs `zypper -q -n list-updates` and parses its output
// via parseZypperListUpdates. Routed through runViaSystemdRunArgv — same
// reasoning as checkDnfUpdates.
func checkZypperUpdates() (map[string]updateInfo, error) {
	ctx, cancel := context.WithTimeout(context.Background(), updateCheckTimeoutSec*time.Second)
	defer cancel()

	result := runViaSystemdRunArgv(ctx, "pkg-check-update", []string{"zypper", "-q", "-n", "list-updates"}, "", updateCheckTimeoutSec, 2*1024*1024)
	if result.Error != "" {
		return nil, fmt.Errorf("zypper list-updates: %s", result.Error)
	}
	if result.ExitCode != 0 {
		return nil, fmt.Errorf("zypper list-updates: exit %d: %s", result.ExitCode, result.Stderr)
	}
	return parseZypperListUpdates(result.Stdout), nil
}

// parseZypperListUpdates parses zypper's pipe-delimited table:
// "S | Repository | Name | Current Version | Available Version | Arch".
// No security classification: zypper models advisories as patches
// (`zypper list-patches`), a different structure than a plain package
// update, and mapping one onto the other isn't attempted.
func parseZypperListUpdates(output string) map[string]updateInfo {
	updates := map[string]updateInfo{}
	for _, line := range strings.Split(output, "\n") {
		if !strings.Contains(line, "|") {
			continue
		}
		fields := strings.Split(line, "|")
		if len(fields) < 6 {
			continue
		}
		for i := range fields {
			fields[i] = strings.TrimSpace(fields[i])
		}
		name, version := fields[2], fields[4]
		if name == "" || name == "Name" {
			continue // header row
		}
		updates[name] = updateInfo{latestVersion: version}
	}
	return updates
}

// packageChecksum returns a stable SHA256 of the sorted package list.
// Sorting ensures the checksum is identical when package order differs.
// Includes LatestVersion so a newly-published update (installed version
// unchanged) still changes the checksum — otherwise the heartbeat's
// unchanged-checksum fast path would skip syncing it to the backend forever.
func packageChecksum(pkgs []Package) string {
	sorted := make([]Package, len(pkgs))
	copy(sorted, pkgs)
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].Name < sorted[j].Name
	})

	h := sha256.New()
	for _, p := range sorted {
		fmt.Fprintf(h, "%s=%s=%s\n", p.Name, p.Version, p.LatestVersion)
	}
	return fmt.Sprintf("%x", h.Sum(nil))
}
