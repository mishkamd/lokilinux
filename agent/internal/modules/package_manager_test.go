package modules

import (
	"reflect"
	"testing"
)

func TestParseDnfCheckUpdate(t *testing.T) {
	// Real check-update shape: a metadata banner, a blank-line-separated
	// package block, and a trailing "Obsoleting Packages" section in a
	// different shape that must be ignored, not misparsed as packages.
	output := `Last metadata expiration check: 0:14:28 ago on Fri 31 Jul 2026 08:05:10 AM EEST.

kernel.x86_64                    5.14.0-570.42.2.el9_6              baseos
kernel-core.x86_64               5.14.0-570.42.2.el9_6              baseos
openssl.x86_64                   1:3.2.2-6.el9_5                    baseos

Obsoleting Packages
python3-requests.noarch          2.32.3-1.el9                       appstream
    obsoletes python3-requests-toolbelt.noarch < 1.0.0-1.el9
`
	got := parseDnfCheckUpdate(output)
	want := map[string]updateInfo{
		"kernel":      {latestVersion: "5.14.0-570.42.2.el9_6"},
		"kernel-core": {latestVersion: "5.14.0-570.42.2.el9_6"},
		"openssl":     {latestVersion: "1:3.2.2-6.el9_5"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("parseDnfCheckUpdate() = %#v, want %#v", got, want)
	}
	if _, ok := got["python3-requests"]; ok {
		t.Error("parseDnfCheckUpdate() should not parse the Obsoleting Packages section as a plain update")
	}
}

func TestParseDnfCheckUpdate_NoUpdates(t *testing.T) {
	got := parseDnfCheckUpdate("Last metadata expiration check: 0:05:00 ago on Fri 31 Jul 2026.\n")
	if len(got) != 0 {
		t.Errorf("parseDnfCheckUpdate() = %#v, want empty map", got)
	}
}

func TestMarkSecurityUpdates(t *testing.T) {
	updates := map[string]updateInfo{
		"openssl":            {latestVersion: "1:3.2.2-6.el9_5"},
		"kernel":             {latestVersion: "5.14.0-570.42.2.el9_6"},
		"python3-requests":   {latestVersion: "2.32.3-1.el9"}, // name itself contains a dash
		"not-in-advisory-at": {latestVersion: "1.0-1.el9"},
	}
	// updateinfo list security output: "advisory  severity  NEVRA"
	secOutput := `FEDORA-EPEL-2024-1234abcd Important/Sec.  openssl-1:3.2.2-6.el9_5.x86_64
FEDORA-EPEL-2024-5678efgh Moderate/Sec.  python3-requests-2.32.3-1.el9.noarch
`
	markSecurityUpdates(secOutput, updates)

	if !updates["openssl"].security {
		t.Error("openssl should be marked security")
	}
	if !updates["python3-requests"].security {
		t.Error("python3-requests (dashed name) should be marked security via prefix match")
	}
	if updates["kernel"].security {
		t.Error("kernel has no advisory in this output, should not be marked security")
	}
	if updates["not-in-advisory-at"].security {
		t.Error("not-in-advisory-at has no advisory, should not be marked security")
	}
}

func TestParseAptUpgradable(t *testing.T) {
	output := `Listing... Done
firefox/jammy-updates 115.0+build3-0ubuntu0.22.04.1 amd64 [upgradable from: 114.0]
libssl3/jammy-security 3.0.2-0ubuntu1.15 amd64 [upgradable from: 3.0.2-0ubuntu1.14]
`
	got := parseAptUpgradable(output)
	want := map[string]updateInfo{
		"firefox": {latestVersion: "115.0+build3-0ubuntu0.22.04.1", security: false},
		"libssl3": {latestVersion: "3.0.2-0ubuntu1.15", security: true},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("parseAptUpgradable() = %#v, want %#v", got, want)
	}
}

func TestParseAptUpgradable_NoUpdates(t *testing.T) {
	got := parseAptUpgradable("Listing... Done\n")
	if len(got) != 0 {
		t.Errorf("parseAptUpgradable() = %#v, want empty map", got)
	}
}

func TestParseZypperListUpdates(t *testing.T) {
	output := `S | Repository          | Name | Current Version | Available Version | Arch
--+---------------------+------+------------------+--------------------+-------
v | Main Repository     | vim  | 8.0-1            | 8.2-1              | x86_64
`
	got := parseZypperListUpdates(output)
	want := map[string]updateInfo{
		"vim": {latestVersion: "8.2-1"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("parseZypperListUpdates() = %#v, want %#v", got, want)
	}
}

func TestApplyUpdateInfo_StaleCacheAfterUpdate(t *testing.T) {
	// A package that was updated after the last check-update cache refresh:
	// installed version now matches the cached "latest", so the stale entry
	// must not still flag it as needing a (security) update.
	pkgs := []Package{{Name: "acl", Version: "2.4.0-1.el9_8"}}
	updates := map[string]updateInfo{
		"acl": {latestVersion: "2.4.0-1.el9_8", security: true},
	}
	applyUpdateInfo(pkgs, updates)

	if pkgs[0].UpdateAvailable {
		t.Error("UpdateAvailable should be false when installed version already equals cached latest version")
	}
	if pkgs[0].IsSecurityUpdate {
		t.Error("IsSecurityUpdate should be false when installed version already equals cached latest version")
	}
	if pkgs[0].LatestVersion != "" {
		t.Errorf("LatestVersion = %q, want empty", pkgs[0].LatestVersion)
	}
}

func TestApplyUpdateInfo_RealUpdatePending(t *testing.T) {
	pkgs := []Package{{Name: "acl", Version: "2.3.1-4.el9"}}
	updates := map[string]updateInfo{
		"acl": {latestVersion: "2.4.0-1.el9_8", security: true},
	}
	applyUpdateInfo(pkgs, updates)

	if !pkgs[0].UpdateAvailable || !pkgs[0].IsSecurityUpdate {
		t.Error("a real pending update (different versions) should still be flagged")
	}
	if pkgs[0].LatestVersion != "2.4.0-1.el9_8" {
		t.Errorf("LatestVersion = %q, want 2.4.0-1.el9_8", pkgs[0].LatestVersion)
	}
}

func TestPackageChecksum_ChangesWithLatestVersion(t *testing.T) {
	base := []Package{{Name: "openssl", Version: "1.0"}}
	updated := []Package{{Name: "openssl", Version: "1.0", LatestVersion: "1.1"}}

	baseSum := packageChecksum(base)
	updatedSum := packageChecksum(updated)

	if baseSum == updatedSum {
		t.Error("packageChecksum should change when LatestVersion changes, even if installed Version doesn't — otherwise a newly-published update is silently skipped by the heartbeat's unchanged-checksum fast path")
	}
}
