// Package ingest also runs on-demand fleet assessments (docs/compliance
// §24) — RunAssessment reuses evaluateAndRecord (the same per-rule
// evidence/exception/platform-filter core snapshot ingest uses) against
// whatever state was most recently collected for each targeted agent. It
// does not force a fresh collection: agents already push snapshots on their
// own heartbeat cadence, and re-running the compliance engine's evaluator
// against the latest stored facts (rather than waiting for the fleet's next
// natural collection cycle) is the actual value an on-demand assessment adds.
package ingest

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/lokilinux/compliance/internal/scope"
	"github.com/lokilinux/compliance/internal/storage"
)

// RunAssessment executes one already-claimed compliance_assessments row end
// to end: resolve scope_selector against the fleet, then for each matched
// agent evaluate every rule in the assessment's policy set (grouped by
// domain, one evaluateAndRecord call per domain against that agent's latest
// stored snapshot for it). Always reaches a terminal FinishAssessment call,
// even on a mid-run error, so an assessment never gets stuck in RUNNING.
// The caller (scheduler.AssessmentPoller) is responsible for claiming
// (storage.ClaimNextPendingAssessment already returns scope_selector and
// policy_set_id, so there's no need to re-fetch them here).
func (in *Ingester) RunAssessment(ctx context.Context, claimed storage.Assessment) error {
	if err := in.runAssessmentBody(ctx, claimed); err != nil {
		_ = in.store.FinishAssessment(ctx, claimed.ID, "FAILED")
		return err
	}
	return in.store.FinishAssessment(ctx, claimed.ID, "COMPLETED")
}

func (in *Ingester) runAssessmentBody(ctx context.Context, claimed storage.Assessment) error {
	if claimed.PolicySetID == nil {
		return fmt.Errorf("assessment %s has no policy_set_id", claimed.ID)
	}

	allAgents, err := in.store.ListAgentAttributes(ctx)
	if err != nil {
		return fmt.Errorf("listing agents for assessment %s: %w", claimed.ID, err)
	}
	matched := matchingAgents(claimed.ScopeSelector, allAgents)

	setRules, err := in.store.RulesForPolicySet(ctx, *claimed.PolicySetID)
	if err != nil {
		return fmt.Errorf("loading rules for assessment %s: %w", claimed.ID, err)
	}
	byDomain := groupRulesByDomain(setRules)

	if err := in.store.SetAssessmentTotals(ctx, claimed.ID, len(matched), len(setRules)*len(matched)); err != nil {
		return err
	}

	for _, agent := range matched {
		rulesDone := 0
		for domain, domainRules := range byDomain {
			latestHash, found, err := in.store.LatestSnapshotHash(ctx, agent.AgentID, domain)
			if err != nil {
				return err
			}
			if !found {
				continue // this agent has never reported this domain — nothing to evaluate against
			}
			body, err := in.store.GetBlobBody(ctx, latestHash)
			if err != nil {
				return err
			}
			var facts map[string]any
			if err := json.Unmarshal(body, &facts); err != nil {
				return fmt.Errorf("decoding latest %s snapshot for assessment %s: %w", domain, claimed.ID, err)
			}

			n, err := in.evaluateAndRecord(ctx, agent.AgentID, agent, domainRules, facts)
			if err != nil {
				return err
			}
			rulesDone += n
		}
		if err := in.store.IncrementAssessmentProgress(ctx, claimed.ID, 1, rulesDone); err != nil {
			return err
		}
	}
	return nil
}

// matchingAgents filters the fleet down to the agents claimed.ScopeSelector
// matches — pure function over already-loaded data, same split as
// baseline.mergeForAgent / policy.MatchingSetIDs, testable without a database.
func matchingAgents(selector map[string]any, agents []storage.AgentAttributes) []storage.AgentAttributes {
	var out []storage.AgentAttributes
	for _, a := range agents {
		if scope.Matches(selector, a.ScopeAttrs()) {
			out = append(out, a)
		}
	}
	return out
}

// groupRulesByDomain buckets a policy set's rules by domain — the evaluator
// works one domain's rules against one domain's fact document at a time.
func groupRulesByDomain(setRules []storage.RuleWithPolicySet) map[string][]storage.RuleWithPolicySet {
	out := make(map[string][]storage.RuleWithPolicySet)
	for _, r := range setRules {
		out[r.Domain] = append(out[r.Domain], r)
	}
	return out
}
