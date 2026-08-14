package ingest

import (
	"testing"

	"github.com/google/uuid"

	"github.com/lokilinux/compliance/internal/rules"
	"github.com/lokilinux/compliance/internal/storage"
)

func TestMatchingAgents_EmptySelectorMatchesEveryAgent(t *testing.T) {
	agents := []storage.AgentAttributes{
		{AgentID: uuid.New(), OsDistro: "rocky"},
		{AgentID: uuid.New(), OsDistro: "ubuntu"},
	}
	got := matchingAgents(map[string]any{}, agents)
	if len(got) != 2 {
		t.Fatalf("matchingAgents(empty selector) = %d agents, want 2", len(got))
	}
}

func TestMatchingAgents_FiltersByAttributes(t *testing.T) {
	rockyID := uuid.New()
	agents := []storage.AgentAttributes{
		{AgentID: rockyID, OsDistro: "rocky"},
		{AgentID: uuid.New(), OsDistro: "ubuntu"},
	}
	got := matchingAgents(map[string]any{"os_distro": "rocky"}, agents)
	if len(got) != 1 || got[0].AgentID != rockyID {
		t.Fatalf("matchingAgents(os_distro=rocky) = %v, want only %s", got, rockyID)
	}
}

func TestGroupRulesByDomain(t *testing.T) {
	setRules := []storage.RuleWithPolicySet{
		{Rule: rules.Rule{ID: "1"}, Domain: "sshd"},
		{Rule: rules.Rule{ID: "2"}, Domain: "sshd"},
		{Rule: rules.Rule{ID: "3"}, Domain: "sysctl"},
	}
	byDomain := groupRulesByDomain(setRules)
	if len(byDomain["sshd"]) != 2 {
		t.Errorf("sshd rules = %d, want 2", len(byDomain["sshd"]))
	}
	if len(byDomain["sysctl"]) != 1 {
		t.Errorf("sysctl rules = %d, want 1", len(byDomain["sysctl"]))
	}
	if len(byDomain) != 2 {
		t.Errorf("domain count = %d, want 2", len(byDomain))
	}
}
