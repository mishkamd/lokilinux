package security

import (
	"testing"
	"time"
)

func TestParseLocalPolicyTopLevelCapabilities(t *testing.T) {
	now := time.Now()
	lp, err := ParseLocalPolicy(map[string]interface{}{
		"version": "v1",
		"capabilities": map[string]interface{}{
			"EXEC_BASH": map[string]interface{}{"enabled": true, "require_approval": true},
		},
	}, now)
	if err != nil {
		t.Fatalf("ParseLocalPolicy: %v", err)
	}
	if lp.Version != "v1" {
		t.Errorf("Version = %q, want %q", lp.Version, "v1")
	}
	rule, ok := lp.Capabilities["EXEC_BASH"]
	if !ok {
		t.Fatalf("capabilities = %v, want EXEC_BASH present", lp.Capabilities)
	}
	if !rule.Enabled || !rule.RequireApproval {
		t.Errorf("rule = %+v, want enabled+require_approval", rule)
	}
}

// The gRPC client delivers the policy one level down under "policies"
// (PolicyConfig wrapper) — that shape is documented in ParseLocalPolicy's
// doc comment and must parse. Regression: the inner type assertion used to
// shadow `ok`, so the outer check always failed and the wrapped shape was
// rejected with "policy has no capabilities object".
func TestParseLocalPolicyNestedPoliciesWrapper(t *testing.T) {
	now := time.Now()
	lp, err := ParseLocalPolicy(map[string]interface{}{
		"policies": map[string]interface{}{
			"version": "v2",
			"capabilities": map[string]interface{}{
				"SERVICE_CONTROL": map[string]interface{}{"enabled": false},
			},
		},
	}, now)
	if err != nil {
		t.Fatalf("ParseLocalPolicy: %v", err)
	}
	if lp.Version != "v2" {
		t.Errorf("Version = %q, want %q", lp.Version, "v2")
	}
	rule, ok := lp.Capabilities["SERVICE_CONTROL"]
	if !ok {
		t.Fatalf("capabilities = %v, want SERVICE_CONTROL present", lp.Capabilities)
	}
	if rule.Enabled {
		t.Errorf("rule = %+v, want disabled", rule)
	}
}

func TestParseLocalPolicyRejectsHopelessShape(t *testing.T) {
	if _, err := ParseLocalPolicy(map[string]interface{}{"version": "v1"}, time.Now()); err == nil {
		t.Fatal("expected an error for a payload without capabilities")
	}
	if _, err := ParseLocalPolicy("not-an-object", time.Now()); err == nil {
		t.Fatal("expected an error for a non-object payload")
	}
}
