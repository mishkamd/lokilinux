package agent

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/lokilinux/agent/internal/security"
	"github.com/lokilinux/agent/internal/storage"
)

func newTestStore(t *testing.T) *storage.Store {
	t.Helper()
	store, err := storage.Open(filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store
}

func newSecFixture(t *testing.T, enforce bool) (configSecurity, *security.Verifier, *security.ReplayStore, func([]byte) string) {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	pubB64 := base64.StdEncoding.EncodeToString(pub)
	v, err := security.NewVerifier(pubB64)
	if err != nil {
		t.Fatal(err)
	}
	store := newTestStore(t)
	cfg := configSecurity{EnforceSignedJobs: enforce}
	return cfg, v, security.NewReplayStore(store), func(unsigned []byte) string {
		return base64.StdEncoding.EncodeToString(ed25519.Sign(priv, unsigned))
	}
}

func signedParams(t *testing.T, sign func([]byte) string, agentID, jobType string, caps []string, nonce string, now time.Time) map[string]interface{} {
	t.Helper()
	e := &security.Envelope{
		JobID:                 "job-1",
		AgentID:               agentID,
		JobType:               jobType,
		Payload:               json.RawMessage(`{}`),
		IssuedAt:              now.Add(-time.Minute).Unix(),
		ExpiresAt:             now.Add(5 * time.Minute).Unix(),
		Nonce:                 nonce,
		RiskLevel:             "HIGH",
		RequestedCapabilities: caps,
	}
	unsigned, err := e.UnsignedBytes()
	if err != nil {
		t.Fatal(err)
	}
	e.Signature = sign(unsigned)
	envJSON, err := json.Marshal(e)
	if err != nil {
		t.Fatal(err)
	}
	var envMap map[string]interface{}
	if err := json.Unmarshal(envJSON, &envMap); err != nil {
		t.Fatal(err)
	}
	return map[string]interface{}{"_envelope": envMap}
}

const testAgentID = "11111111-2222-4333-8444-555555555555"

func TestUnsignedJobRejectedWhenEnforced(t *testing.T) {
	cfg, v, rp, _ := newSecFixture(t, true)
	res := validateAndAuthorize(cfg, v, rp, nil, testAgentID, "job-1", "SERVICE",
		map[string]interface{}{}, "", time.Now())
	if res == nil || res.ExitCode != 126 {
		t.Fatalf("unsigned privileged job not rejected: %+v", res)
	}
}

func TestUnsignedJobAllowedInObservabilityMode(t *testing.T) {
	cfg, v, rp, _ := newSecFixture(t, false)
	res := validateAndAuthorize(cfg, v, rp, nil, testAgentID, "job-1", "SERVICE",
		map[string]interface{}{}, "", time.Now())
	if res != nil {
		t.Fatalf("observability mode must allow: %+v", res)
	}
}

func TestSignedJobAccepted(t *testing.T) {
	cfg, v, rp, sign := newSecFixture(t, true)
	now := time.Now()
	params := signedParams(t, sign, testAgentID, "SERVICE", []string{"SERVICE_CONTROL"}, "n1", now)
	res := validateAndAuthorize(cfg, v, rp, nil, testAgentID, "job-1", "SERVICE", params, "", now)
	if res != nil {
		t.Fatalf("valid signed job rejected: %+v", res)
	}
}

func TestReplayRejected(t *testing.T) {
	cfg, v, rp, sign := newSecFixture(t, true)
	now := time.Now()
	pol := &security.LocalPolicy{
		Version:      "t",
		ReceivedAt:   now,
		Capabilities: map[string]security.CapabilityRule{"PACKAGE_MANAGEMENT": {Enabled: true}},
	}
	params := signedParams(t, sign, testAgentID, "PACKAGE_UPDATE", []string{"PACKAGE_MANAGEMENT"}, "nonce-dup", now)
	if res := validateAndAuthorize(cfg, v, rp, pol, testAgentID, "job-1", "PACKAGE_UPDATE", params, "", now); res != nil {
		t.Fatalf("first run rejected: %+v", res)
	}
	params2 := signedParams(t, sign, testAgentID, "PACKAGE_UPDATE", []string{"PACKAGE_MANAGEMENT"}, "nonce-dup", now)
	if res := validateAndAuthorize(cfg, v, rp, pol, testAgentID, "job-2", "PACKAGE_UPDATE", params2, "", now); res == nil {
		t.Fatal("replayed nonce accepted")
	} else if !contains(res.Error, "duplicate_job") {
		t.Fatalf("wrong reject code: %s", res.Error)
	}
}

func TestHighRiskWithoutPolicyRejected(t *testing.T) {
	cfg, v, rp, sign := newSecFixture(t, true)
	now := time.Now()
	params := signedParams(t, sign, testAgentID, "PACKAGE_UPDATE", []string{"PACKAGE_MANAGEMENT"}, "n7", now)
	res := validateAndAuthorize(cfg, v, rp, nil, testAgentID, "job-1", "PACKAGE_UPDATE", params, "", now)
	if res == nil || !contains(res.Error, "policy_missing") {
		t.Fatalf("HIGH risk without policy accepted: %+v", res)
	}
}

func TestStalePolicyRejectedAndDisabledCapRejected(t *testing.T) {
	cfg, v, rp, sign := newSecFixture(t, true)
	now := time.Now()
	stale := &security.LocalPolicy{Version: "old", ReceivedAt: now.Add(-48 * time.Hour),
		Capabilities: map[string]security.CapabilityRule{"PACKAGE_MANAGEMENT": {Enabled: true}}}
	params := signedParams(t, sign, testAgentID, "PACKAGE_UPDATE", []string{"PACKAGE_MANAGEMENT"}, "n8", now)
	if res := validateAndAuthorize(cfg, v, rp, stale, testAgentID, "job-1", "PACKAGE_UPDATE", params, "", now); res == nil || !contains(res.Error, "policy_stale") {
		t.Fatalf("stale policy accepted: %+v", res)
	}
	disabled := &security.LocalPolicy{Version: "new", ReceivedAt: now,
		Capabilities: map[string]security.CapabilityRule{"PACKAGE_MANAGEMENT": {Enabled: false}}}
	params2 := signedParams(t, sign, testAgentID, "PACKAGE_UPDATE", []string{"PACKAGE_MANAGEMENT"}, "n9", now)
	if res := validateAndAuthorize(cfg, v, rp, disabled, testAgentID, "job-1", "PACKAGE_UPDATE", params2, "", now); res == nil || !contains(res.Error, "capability_disabled") {
		t.Fatalf("disabled capability accepted: %+v", res)
	}
}

func TestPolicyRoundTripAndShapes(t *testing.T) {
	now := time.Now()
	lp, err := security.ParseLocalPolicy(map[string]interface{}{
		"version": "v1",
		"capabilities": map[string]interface{}{
			"service_control": map[string]interface{}{"enabled": true},
			"EXEC_BASH":       true,
			"PLUGIN_INSTALL":  false,
		},
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	if !lp.Capabilities["SERVICE_CONTROL"].Enabled {
		t.Fatal("nested rule enabled lost")
	}
	if lp.Capabilities["EXEC_BASH"].Enabled != true {
		t.Fatal("boolean shorthand lost")
	}
	if lp.Capabilities["PLUGIN_INSTALL"].Enabled {
		t.Fatal("disabled flag lost")
	}
	blob, _ := lp.Marshal()
	back, err := security.UnmarshalLocalPolicy(blob)
	if err != nil || back.Version != "v1" || len(back.Capabilities) != 3 {
		t.Fatalf("kv round trip broken: %v %v", back, err)
	}
}

func TestWrongAgentRejected(t *testing.T) {
	cfg, v, rp, sign := newSecFixture(t, true)
	now := time.Now()
	params := signedParams(t, sign, "OTHER-AGENT", "REBOOT", []string{"REBOOT_HOST"}, "n3", now)
	res := validateAndAuthorize(cfg, v, rp, nil, testAgentID, "job-1", "REBOOT", params, "", now)
	if res == nil || !contains(res.Error, "wrong_agent") {
		t.Fatalf("cross-agent envelope accepted: %+v", res)
	}
}

func TestCapabilityGapRejected(t *testing.T) {
	cfg, v, rp, sign := newSecFixture(t, true)
	now := time.Now()
	// REBOOT needs REBOOT_HOST; envelope claims only READ_SYSTEM
	params := signedParams(t, sign, testAgentID, "REBOOT", []string{"READ_SYSTEM"}, "n4", now)
	res := validateAndAuthorize(cfg, v, rp, nil, testAgentID, "job-1", "REBOOT", params, "", now)
	if res == nil || !contains(res.Error, "capability_gap") {
		t.Fatalf("capability gap not caught: %+v", res)
	}
}

func TestPayloadMismatchRejected(t *testing.T) {
	cfg, v, rp, sign := newSecFixture(t, true)
	now := time.Now()
	params := signedParams(t, sign, testAgentID, "SERVICE", []string{"SERVICE_CONTROL"}, "n6", now)
	// swap the outer parameters after signing — signature stays valid, but
	// it no longer covers what would execute
	params["service_name"] = "sshd"
	res := validateAndAuthorize(cfg, v, rp, nil, testAgentID, "job-1", "SERVICE", params, "", now)
	if res == nil || !contains(res.Error, "payload_mismatch") {
		t.Fatalf("parameter swap not caught: %+v", res)
	}
}

func TestUnknownJobTypeRejectedWhenEnforced(t *testing.T) {
	cfg, v, rp, sign := newSecFixture(t, true)
	now := time.Now()
	params := signedParams(t, sign, testAgentID, "TOTALLY_NEW_TYPE", []string{"EXEC_BASH"}, "n5", now)
	res := validateAndAuthorize(cfg, v, rp, nil, testAgentID, "job-1", "TOTALLY_NEW_TYPE", params, "", now)
	if res == nil || !contains(res.Error, "unknown_capability") {
		t.Fatalf("unregistered type accepted: %+v", res)
	}
}

func TestWorkflowStepsDemandAnsibleCap(t *testing.T) {
	stepsJSON := `[{"sequence":1,"type":"ansible","params":{}}]`
	caps := security.RequiredCapabilities("WORKFLOW_STEPS", stepsJSON)
	found := false
	for _, c := range caps {
		if c == security.CapExecAnsible {
			found = true
		}
	}
	if !found {
		t.Fatalf("ansible step did not demand EXEC_ANSIBLE: %v", caps)
	}
}

func contains(s, sub string) bool { return strings.Contains(s, sub) }
