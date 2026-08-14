// Package scope holds the scope_selector matching + platform-id logic
// shared by baseline resolution (internal/baseline) and policy set
// resolution (internal/policy) — both match an agent against a
// scope_selector JSONB blob the same way, so the algorithm lives here once.
package scope

import "strings"

// AgentAttributes is the subset of an agent's identity a selector can match
// against. Mirrors storage.AgentAttributes' matchable fields (deliberately
// not importing storage here — this package has zero internal dependencies
// so both baseline and policy can depend on it without a cycle).
type AgentAttributes struct {
	OsDistro  string
	OsVersion string
	Category  string
	Project   string
}

// Matches evaluates a scope_selector against an agent's attributes. An
// empty selector (GLOBAL) matches everything. See baseline.selectorMatches'
// original doc (docs/compliance/06-BASELINE.md §1) for why environment
// aliases to category and application to project, and why role/datacenter/
// cluster never match — moved here verbatim so policy set scope resolution
// (docs/compliance/07-POLICY-ENGINE.md) uses the identical rule.
func Matches(selector map[string]any, attrs AgentAttributes) bool {
	if len(selector) == 0 {
		return true
	}
	attrValues := map[string]string{
		"os_distro":   strings.ToLower(attrs.OsDistro),
		"os_version":  strings.ToLower(attrs.OsVersion),
		"category":    strings.ToLower(attrs.Category),
		"environment": strings.ToLower(attrs.Category),
		"project":     strings.ToLower(attrs.Project),
		"application": strings.ToLower(attrs.Project),
	}
	for key, want := range selector {
		wantStr, ok := want.(string)
		if !ok {
			return false // non-string selector value can never match
		}
		got, ok := attrValues[key]
		if !ok || !strings.EqualFold(got, wantStr) {
			return false
		}
	}
	return true
}

// PlatformID derives the compliance_rules.platform_filter identifier from
// an agent's raw os-release fields (agent/internal/modules/system_info.go
// reads ID/VERSION_ID verbatim: osDistro="rocky", osVersion="9.8"). The
// major version only — a rule scoped to "rocky9" applies across every rocky
// 9.x point release, matching how ComplianceAsCode content itself is
// versioned by major release, never by point release.
func PlatformID(osDistro, osVersion string) string {
	distro := strings.ToLower(strings.TrimSpace(osDistro))
	major, _, _ := strings.Cut(strings.TrimSpace(osVersion), ".")
	if distro == "" || major == "" {
		return ""
	}
	return distro + major
}

// PlatformApplicable reports whether platformFilter (compliance_rules.
// platform_filter, e.g. ["rhel9","oracle_linux9","rocky9"]) permits
// evaluation on platform. An empty filter means "every platform" — most
// rules (sysctl, users, sudo) aren't OS-specific, so requiring every rule
// to enumerate every supported distro would be false precision.
func PlatformApplicable(platformFilter []string, platform string) bool {
	if len(platformFilter) == 0 {
		return true
	}
	if platform == "" {
		return false // agent's platform is unknown — cannot claim applicability
	}
	for _, p := range platformFilter {
		if strings.EqualFold(p, platform) {
			return true
		}
	}
	return false
}
