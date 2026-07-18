package modules

import (
	"crypto/sha256"
	"fmt"
	"os"
	"os/exec"
	"sort"
	"strings"
	"time"
)

// Package represents a single installed system package.
type Package struct {
	Name         string
	Version      string
	Architecture string
	InstalledAt  time.Time
}

// PackageManagerModule detects the distro package manager and lists installed packages.
type PackageManagerModule struct{}

func NewPackageManagerModule() *PackageManagerModule { return &PackageManagerModule{} }

// ListPackages returns all installed packages and a SHA256 checksum of the list.
// The checksum is used by the heartbeat to detect inventory changes without
// sending the full list every cycle.
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

	checksum := packageChecksum(pkgs)
	return pkgs, checksum, nil
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

// packageChecksum returns a stable SHA256 of the sorted package list.
// Sorting ensures the checksum is identical when package order differs.
func packageChecksum(pkgs []Package) string {
	sorted := make([]Package, len(pkgs))
	copy(sorted, pkgs)
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].Name < sorted[j].Name
	})

	h := sha256.New()
	for _, p := range sorted {
		fmt.Fprintf(h, "%s=%s\n", p.Name, p.Version)
	}
	return fmt.Sprintf("%x", h.Sum(nil))
}
