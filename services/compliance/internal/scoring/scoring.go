// Package scoring maps a compliance domain to one of the five brief-
// specified score buckets (docs/compliance/07-POLICY-ENGINE.md §4).
//
// CategoryByDomain mirrors backend/lokilinux/services/report_service.py's
// CATEGORY_BY_DOMAIN exactly — deliberately duplicated rather than shared,
// same precedent as ingest.canonicalHash mirroring the agent's
// canonical.go: this Go service and the Python backend are separate
// deployables with no shared internal package today.
package scoring

var CategoryByDomain = map[string]string{
	"sshd":             "security",
	"pam":              "security",
	"auditd":           "security",
	"sudo":             "security",
	"selinux":          "security",
	"firewall":         "security",
	"sysctl":           "configuration",
	"systemd_services": "configuration",
	"cron":             "configuration",
	"login_defs":       "configuration",
	"password_policy":  "configuration",
	"network":          "configuration",
	"time_sync":        "configuration",
	"mounts":           "filesystem",
	"file_integrity":   "filesystem",
	"repositories":     "filesystem",
	"kernel":           "kernel",
	"kernel_modules":   "kernel",
}

// Classify returns the score category for a domain, defaulting to
// "configuration" for anything not in the table — an unclassified domain
// still counts toward some category rather than silently vanishing from
// scoring.
func Classify(domain string) string {
	if c, ok := CategoryByDomain[domain]; ok {
		return c
	}
	return "configuration"
}
