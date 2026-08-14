// Package policy resolves which policy sets apply to an agent by matching
// policy_assignments.scope_selector against the agent's attributes — the
// same scope-tree matching internal/baseline uses for baselines
// (docs/compliance/07-POLICY-ENGINE.md), extracted to internal/scope so
// both packages share one algorithm.
package policy

import (
	"github.com/google/uuid"

	"github.com/lokilinux/compliance/internal/scope"
	"github.com/lokilinux/compliance/internal/storage"
)

// MatchingSetIDs returns the policy_set_id of every assignment whose
// scope_selector matches attrs — a pure function of already-loaded data
// (mirrors internal/baseline's mergeForAgent split) so it's unit-testable
// without a database. Order is not significant: rule loading downstream
// deduplicates via SELECT DISTINCT.
func MatchingSetIDs(attrs storage.AgentAttributes, assignments []storage.PolicyAssignment) []uuid.UUID {
	sAttrs := scope.AgentAttributes{
		OsDistro: attrs.OsDistro, OsVersion: attrs.OsVersion,
		Category: attrs.Category, Project: attrs.Project,
	}
	var out []uuid.UUID
	for _, a := range assignments {
		if scope.Matches(a.ScopeSelector, sAttrs) {
			out = append(out, a.PolicySetID)
		}
	}
	return out
}
