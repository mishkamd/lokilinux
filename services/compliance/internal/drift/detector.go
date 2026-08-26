// Package drift compares an agent's current facts document against its
// previous snapshot (and, once baseline_effective has a real writer, its
// baseline) to produce drift_events. See docs/compliance/08-DRIFT-FIM.md.
package drift

import (
	"reflect"
	"sort"
	"strconv"
)

// ComparedAgainst mirrors drift_events.compared_against.
type ComparedAgainst string

const (
	ComparedAgainstBaseline         ComparedAgainst = "BASELINE"
	ComparedAgainstPreviousSnapshot ComparedAgainst = "PREVIOUS_SNAPSHOT"
)

// Severity mirrors drift_events.severity.
type Severity string

const (
	SeverityLow      Severity = "LOW"
	SeverityMedium   Severity = "MEDIUM"
	SeverityHigh     Severity = "HIGH"
	SeverityCritical Severity = "CRITICAL"
)

// ChangeType mirrors drift_events.change_type.
//
// ponytail: only CONFIG_MODIFIED is actually classified today. The fuller
// enum in docs/compliance/08-DRIFT-FIM.md (USER_ADDED, PACKAGE_CHANGED,
// SELINUX_CHANGED, ...) needs domain-aware shape knowledge this package
// doesn't have yet — the only collector that exists is sshd
// (agent/internal/compliance/sshd_collector.go), a flat key-value map, not
// a list of users or packages. Add cases here as domain-specific collectors
// (and their known field shapes) land, rather than guessing ahead of them.
type ChangeType string

const ChangeTypeConfigModified ChangeType = "CONFIG_MODIFIED"

// FieldDiff is one changed leaf value, addressed by a JSON-pointer-style
// path (e.g. "/PermitRootLogin") — the same format drift_details.field_path
// stores, so the frontend diff viewer can render it directly.
type FieldDiff struct {
	FieldPath string
	OldValue  any
	NewValue  any
}

// Event is one detected drift occurrence, ready to become a drift_events
// row (+ one drift_details row per FieldDiff).
type Event struct {
	Domain          string
	ComparedAgainst ComparedAgainst
	Severity        Severity
	ChangeType      ChangeType
	Summary         string
	FieldDiffs      []FieldDiff
}

// severityByDomain is the default classification table from
// docs/compliance/08-DRIFT-FIM.md §3 — overridable per policy assignment in
// a future iteration; this is the fleet-wide default, not a hardcoded
// ceiling with no escape hatch.
var severityByDomain = map[string]Severity{
	"selinux":          SeverityCritical,
	"firewall":         SeverityCritical,
	"sudo":             SeverityCritical,
	"pam":              SeverityCritical,
	"users":            SeverityHigh,
	"groups":           SeverityHigh,
	"auditd":           SeverityHigh,
	"sshd":             SeverityHigh,
	"capabilities":     SeverityHigh,
	"sysctl":           SeverityMedium,
	"systemd_services": SeverityMedium,
	"cron":             SeverityMedium,
	"mounts":           SeverityLow,
	"time_sync":        SeverityLow,
	"dns":              SeverityLow,
}

// ClassifySeverity returns the default severity for a domain, defaulting to
// MEDIUM for any domain not in the table (an unclassified domain is a gap
// to fill, not silently LOW-risk).
func ClassifySeverity(domain string) Severity {
	if s, ok := severityByDomain[domain]; ok {
		return s
	}
	return SeverityMedium
}

// Detect runs a structural diff between old and new facts documents and
// returns nil if they're equal — callers decide whether "no drift" is worth
// recording at all (it isn't; Ingester only calls this when hashes differ).
func Detect(domain string, comparedAgainst ComparedAgainst, oldFacts, newFacts map[string]any) *Event {
	diffs := diffDocuments("", oldFacts, newFacts)
	if len(diffs) == 0 {
		return nil
	}
	sort.Slice(diffs, func(i, j int) bool { return diffs[i].FieldPath < diffs[j].FieldPath })

	return &Event{
		Domain:          domain,
		ComparedAgainst: comparedAgainst,
		Severity:        ClassifySeverity(domain),
		ChangeType:      ChangeTypeConfigModified,
		Summary:         summarize(domain, diffs),
		FieldDiffs:      diffs,
	}
}

// diffDocuments walks both documents structurally (not a text diff —
// canonical documents are deterministically key-ordered already, so a
// structural walk is both cheaper and immune to whitespace/ordering false
// positives a text diff would produce).
func diffDocuments(prefix string, old, new_ any) []FieldDiff {
	var out []FieldDiff

	newMap, newIsMap := new_.(map[string]any)
	oldMap, oldIsMap := old.(map[string]any)

	if newIsMap || oldIsMap {
		keys := unionKeys(oldMap, newMap)
		for _, k := range keys {
			var oldChild, newChild any
			if oldMap != nil {
				oldChild = oldMap[k]
			}
			if newMap != nil {
				newChild = newMap[k]
			}
			out = append(out, diffDocuments(prefix+"/"+k, oldChild, newChild)...)
		}
		return out
	}

	if !reflect.DeepEqual(old, new_) {
		out = append(out, FieldDiff{FieldPath: prefix, OldValue: old, NewValue: new_})
	}
	return out
}

func unionKeys(a, b map[string]any) []string {
	seen := make(map[string]struct{}, len(a)+len(b))
	var keys []string
	for k := range a {
		if _, ok := seen[k]; !ok {
			seen[k] = struct{}{}
			keys = append(keys, k)
		}
	}
	for k := range b {
		if _, ok := seen[k]; !ok {
			seen[k] = struct{}{}
			keys = append(keys, k)
		}
	}
	sort.Strings(keys) // deterministic FieldDiff order, independent of Go's random map iteration
	return keys
}

func summarize(domain string, diffs []FieldDiff) string {
	if len(diffs) == 1 {
		return domain + ": " + diffs[0].FieldPath + " changed"
	}
	return domain + ": " + strconv.Itoa(len(diffs)) + " fields changed"
}
