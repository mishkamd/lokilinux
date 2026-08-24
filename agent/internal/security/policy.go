package security

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// LocalPolicy is the agent-side cache of the control-plane policy delivered
// over the heartbeat's update_policy channel (PolicyConfig.Policies Struct).
// Shape (tolerant parse, plan §9):
//
//	{"version": "...", "capabilities": {
//	    "SERVICE_CONTROL": {"enabled": true},
//	    "EXEC_BASH": {"enabled": true, "require_approval": true}}}
//
// Fail-closed semantics: HIGH/CRITICAL capabilities require a FRESH enabled
// policy entry; absence or staleness of the whole document blocks them.
type LocalPolicy struct {
	Version      string                     `json:"version"`
	Capabilities map[string]CapabilityRule  `json:"capabilities"`
	ReceivedAt   time.Time                  `json:"received_at"`
}

// CapabilityRule is the per-capability gate.
type CapabilityRule struct {
	Enabled         bool `json:"enabled"`
	RequireApproval bool `json:"require_approval"`
}

// MaxAge bounds policy freshness for HIGH+ enforcement.
const MaxAge = 24 * time.Hour

// ParseLocalPolicy normalizes an arbitrary decoded JSON value (as delivered
// by the heartbeat map) into a LocalPolicy. Accepted shapes: capabilities
// object at the top level, or one level down under "policies" (the
// PolicyConfig wrapper the gRPC client produces). Returns error on hopeless
// shapes so callers keep the previous good policy rather than clobbering it.
func ParseLocalPolicy(raw interface{}, now time.Time) (*LocalPolicy, error) {
	m, ok := raw.(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("policy payload is not an object")
	}
	lp := &LocalPolicy{Capabilities: map[string]CapabilityRule{}, ReceivedAt: now}
	if v, ok := m["version"].(string); ok {
		lp.Version = v
	}
	capsRaw, ok := m["capabilities"].(map[string]interface{})
	if !ok {
		if inner, ok := m["policies"].(map[string]interface{}); ok {
			capsRaw, ok = inner["capabilities"].(map[string]interface{})
			if v, okv := inner["version"].(string); okv && lp.Version == "" {
				lp.Version = v
			}
		}
	}
	if !ok {
		return nil, fmt.Errorf("policy has no capabilities object")
	}
	for name, ruleRaw := range capsRaw {
		name = strings.ToUpper(strings.TrimSpace(name))
		rule := CapabilityRule{Enabled: true} // presence without fields = enabled
		switch r := ruleRaw.(type) {
		case bool:
			rule.Enabled = r
		case map[string]interface{}:
			if b, ok := r["enabled"].(bool); ok {
				rule.Enabled = b
			}
			if b, ok := r["require_approval"].(bool); ok {
				rule.RequireApproval = b
			}
		}
		lp.Capabilities[name] = rule
	}
	return lp, nil
}

type PolicyRejectReason string

const (
	PolicyStale     PolicyRejectReason = "policy_stale"
	PolicyMissing   PolicyRejectReason = "policy_missing"
	CapabilityOff   PolicyRejectReason = "capability_disabled"
	ApprovalNeeded  PolicyRejectReason = "approval_required"
)

func riskTier(risk string) int {
	switch RiskLevel(risk) {
	case RiskCritical:
		return 3
	case RiskHigh:
		return 2
	case RiskMedium:
		return 1
	default:
		return 0
	}
}

// EvaluateAuthorizations applies the plan §27/§28 matrix to every capability
// a job demands. LOW/MEDIUM pass without policy; HIGH/CRITICAL require a
// fresh, enabled policy entry. require_approval entries reject until the
// approval-claim mechanism ships (explicit, not silent).
func (lp *LocalPolicy) EvaluateAuthorizations(capabilities []string, risksByCap func(string) string, now time.Time) (PolicyRejectReason, string) {
	for _, capName := range capabilities {
		tier := riskTier(risksByCap(capName))
		if tier < 2 {
			continue // LOW/MEDIUM: no local policy requirement
		}
		if lp == nil {
			return PolicyMissing, fmt.Sprintf("capability %s requires policy, none cached", capName)
		}
		if now.Sub(lp.ReceivedAt) > MaxAge {
			return PolicyStale, fmt.Sprintf("policy received at %s exceeds %s", lp.ReceivedAt.Format(time.RFC3339), MaxAge)
		}
		rule, ok := lp.Capabilities[capName]
		if !ok {
			return CapabilityOff, fmt.Sprintf("capability %s absent from policy", capName)
		}
		if !rule.Enabled {
			return CapabilityOff, fmt.Sprintf("capability %s disabled by policy", capName)
		}
		if rule.RequireApproval {
			return ApprovalNeeded, fmt.Sprintf("capability %s requires approval flow (not yet available)", capName)
		}
	}
	return "", ""
}

// Marshal serializes for the agent_config KV store.
func (lp *LocalPolicy) Marshal() ([]byte, error) { return json.Marshal(lp) }

// UnmarshalLocalPolicy restores from the KV store.
func UnmarshalLocalPolicy(b []byte) (*LocalPolicy, error) {
	var lp LocalPolicy
	if err := json.Unmarshal(b, &lp); err != nil {
		return nil, err
	}
	if lp.Capabilities == nil {
		lp.Capabilities = map[string]CapabilityRule{}
	}
	return &lp, nil
}
