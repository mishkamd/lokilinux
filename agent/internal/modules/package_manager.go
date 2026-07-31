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

// cveRef is one CVE advisory affecting a package, from `dnf updateinfo list
// cves` (see checkDnfCVEs). Severity is already mapped to the backend's
// CRITICAL/HIGH/MEDIUM/LOW vocabulary (schemas/cve.py CVESeverity), not the
// proto comment's lowercase suggestion — there was no other severity string
// on the wire yet to conflict with, and this is what the backend/frontend
// actually expect and render.
type cveRef struct {
	cveID    string
	severity string
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
	cves      map[string][]cveRef // package name -> CVEs it's vulnerable to (dnf/yum only)
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
	applyUpdateInfo(pkgs, updates)

	checksum := packageChecksum(pkgs)
	return pkgs, checksum, nil
}

// applyUpdateInfo merges cached update-check results into pkgs in place.
// Guards against stale cache: the check-update cache lives for up to
// updateCheckInterval, so a package updated moments ago (installed version
// collection is never cached, unlike this map) can still show up here with
// its pre-update advisory — installed version now equals the cached
// "latest", yet the stale entry would still flag it as needing a security
// update. Comparing versions before setting the flags fixes that
// contradiction regardless of why the cache is stale.
func applyUpdateInfo(pkgs []Package, updates map[string]updateInfo) {
	for i := range pkgs {
		info, ok := updates[pkgs[i].Name]
		if !ok || info.latestVersion == pkgs[i].Version {
			continue
		}
		pkgs[i].LatestVersion = info.latestVersion
		pkgs[i].UpdateAvailable = true
		pkgs[i].IsSecurityUpdate = info.security
	}
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

	// CVE lookup only exists for dnf/yum (see checkDnfCVEs) — apt/zypper
	// leave m.cves nil, same honest-gap precedent as zypper's missing
	// security classification below.
	if pm == "dnf" || pm == "yum" {
		m.cves = checkDnfCVEs(pm, updates)
	} else {
		m.cves = nil
	}

	return updates
}

// Vulnerabilities cross-references the cached CVE lookup (dnf/yum only, see
// refreshUpdates) against pkgs to produce one Vulnerability per (package,
// CVE) pair: installed version comes from pkgs (authoritative, collected
// fresh every call), fixed version comes from the same updates cache the
// CVE was matched against (a CVE is only ever listed for a package that has
// a pending update to fix it, so the two caches always agree on which
// packages are in scope). Returns nil for apt/zypper — no CVE source wired
// for them yet, not a fake "scanned, found none".
func (m *PackageManagerModule) Vulnerabilities(pkgs []Package) []Vulnerability {
	m.mu.Lock()
	cves := m.cves
	updates := m.updates
	m.mu.Unlock()

	if len(cves) == 0 {
		return nil
	}

	installed := make(map[string]string, len(pkgs))
	for _, p := range pkgs {
		installed[p.Name] = p.Version
	}

	var vulns []Vulnerability
	for name, refs := range cves {
		for _, ref := range refs {
			vulns = append(vulns, Vulnerability{
				CVEId:        ref.cveID,
				PackageName:  name,
				InstalledVer: installed[name],
				FixedVer:     updates[name].latestVersion,
				Severity:     ref.severity,
			})
		}
	}
	return vulns
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

// checkDnfCVEs runs `<bin> updateinfo list cves` and parses its output via
// parseDnfCVEs. Best-effort like the security-advisory lookup next to it in
// checkDnfUpdates: a failed CVE lookup doesn't invalidate the update list,
// packages just won't have CVE detail attached. Needs the same
// systemd-run escape hatch as every other dnf invocation here.
func checkDnfCVEs(bin string, updates map[string]updateInfo) map[string][]cveRef {
	ctx, cancel := context.WithTimeout(context.Background(), updateCheckTimeoutSec*time.Second)
	defer cancel()

	result := runViaSystemdRunArgv(ctx, "pkg-check-update-cves", []string{bin, "updateinfo", "list", "cves"}, "", updateCheckTimeoutSec, 2*1024*1024)
	if result.Error != "" || result.ExitCode != 0 {
		slog.Default().Warn("dnf updateinfo list cves failed", "error", result.Error, "exit_code", result.ExitCode)
		return nil
	}
	return parseDnfCVEs(result.Stdout, updates)
}

// dnfSeverityToBackend maps Red Hat's advisory severity words (as printed by
// `updateinfo list cves`) to the CRITICAL/HIGH/MEDIUM/LOW vocabulary already
// used by schemas/cve.py's CVESeverity — the standard CVSS-range mapping
// Red Hat itself documents (Critical 9.0-10, Important≈High 7.0-8.9,
// Moderate≈Medium 4.0-6.9, Low 0.1-3.9).
var dnfSeverityToBackend = map[string]string{
	"Critical":  "CRITICAL",
	"Important": "HIGH",
	"Moderate":  "MEDIUM",
	"Low":       "LOW",
}

// parseDnfCVEs parses `dnf/yum updateinfo list cves` stdout: 3 whitespace
// columns "advisory-id severity/Sec. NEVRA" — except `updateinfo list cves`
// also includes non-security advisories with a CVE association, printed
// with a "bugfix" (or similar) 2nd column instead of "<Word>/Sec." — those
// are skipped, they carry no CVSS-style severity to map and aren't a
// vulnerability record in this schema's sense (confirmed live: real output
// mixes both). NEVRA->package name uses the same prefix-match technique as
// markSecurityUpdates, against updates' keys — a CVE is only ever listed
// here for a package that also has a pending update to fix it, so the two
// always share the same name set. Unlike markSecurityUpdates (a single
// bool, a false positive there is harmless), picking the *longest* matching
// name matters here: a NEVRA for "python3-libs-..." also starts with
// "python3-", so taking every prefix match would mis-attribute that CVE to
// "python3" too — longest-prefix-match picks the one real owner.
func parseDnfCVEs(output string, updates map[string]updateInfo) map[string][]cveRef {
	result := map[string][]cveRef{}
	for _, line := range strings.Split(output, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 3 {
			continue
		}
		cveID, sevType, nevra := fields[0], fields[1], fields[len(fields)-1]
		sevWord, ok := strings.CutSuffix(sevType, "/Sec.")
		if !ok {
			continue
		}
		severity, ok := dnfSeverityToBackend[sevWord]
		if !ok {
			continue
		}
		best := ""
		for name := range updates {
			if strings.HasPrefix(nevra, name+"-") && len(name) > len(best) {
				best = name
			}
		}
		if best != "" {
			result[best] = append(result[best], cveRef{cveID: cveID, severity: severity})
		}
	}
	return result
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
