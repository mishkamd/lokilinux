package agent

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"github.com/lokilinux/agent/internal/security"
)

// TestApprovalClaimSatisfiesRequireApproval: full pipeline — policy demands
// approval for PACKAGE_MANAGEMENT; a valid signed claim unlocks execution.
func TestApprovalClaimSatisfiesRequireApproval(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	set := map[int]string{1: base64.StdEncoding.EncodeToString(pub)}
	verifier, err := security.NewVerifierSet(set, nil)
	if err != nil {
		t.Fatal(err)
	}
	store := newTestStore(t)
	rp := security.NewReplayStore(store)
	cfg := configSecurity{EnforceSignedJobs: true}
	now := time.Now()

	jobHash := fmtHash([]byte(`{"package_names":["nginx"]}`))
	claim := buildClaim(t, priv, "job-9", jobHash, "agent-x", []string{"PACKAGE_MANAGEMENT"}, now)

	params := signedParamsWithPayload(t,
		func(b []byte) string { return b64(ed25519.Sign(priv, b)) },
		"agent-x", "PACKAGE_UPDATE", []string{"PACKAGE_MANAGEMENT"},
		"nonce-claim", now, rawJSON(`{"package_names":["nginx"]}`))
	params["_approval_claim"] = claimMap(claim)

	pol := &security.LocalPolicy{Version: "p", ReceivedAt: now,
		Capabilities: map[string]security.CapabilityRule{
			"PACKAGE_MANAGEMENT": {Enabled: true, RequireApproval: true},
		}}

	res := validateAndAuthorize(cfg, verifier, rp, pol, "agent-x", "job-9",
		"PACKAGE_UPDATE", params, "", now)
	if res != nil {
		t.Fatalf("valid claim should satisfy require_approval: %+v", res)
	}

	// replay of the SAME claim (fresh envelope) must now fail
	params2 := signedParamsWithPayload(t,
		func(b []byte) string { return b64(ed25519.Sign(priv, b)) },
		"agent-x", "PACKAGE_UPDATE", []string{"PACKAGE_MANAGEMENT"},
		"nonce-fresh-envelope", now, rawJSON(`{"package_names":["nginx"]}`))
	params2["_approval_claim"] = claimMap(claim)
	res2 := validateAndAuthorize(cfg, verifier, rp, pol, "agent-x", "job-9",
		"PACKAGE_UPDATE", params2, "", now)
	if res2 == nil || !contains(res2.Error, "replayed") {
		t.Fatalf("claim replay accepted: %+v", res2)
	}
}

// ── helpers ──────────────────────────────────────────────────────────────────

func b64(b []byte) string { return base64.StdEncoding.EncodeToString(b) }
func fmtHash(b []byte) string { return fmt.Sprintf("%x", sha256.Sum256(security.MustCanonical(b))) }

func rawJSON(s string) json.RawMessage { return json.RawMessage(s) }

func buildClaim(t *testing.T, priv ed25519.PrivateKey, jobID, jobHash, target string, caps []string, now time.Time) map[string]interface{} {
	t.Helper()
	claim := map[string]interface{}{
		"approval_id":     "appr-1",
		"job_id":          jobID,
		"job_hash":        jobHash,
		"target_agent_id": target,
		"capabilities":    caps,
		"approver_id":     "admin@x",
		"issued_at":       now.Add(-time.Minute).Unix(),
		"expires_at":      now.Add(5 * time.Minute).Unix(),
		"nonce":           "claim-nonce-1",
		"signature":       "",
	}
	unsigned, err := json.Marshal(claim)
	if err != nil {
		t.Fatal(err)
	}
	canonical, err := security.Canonical(unsigned)
	if err != nil {
		t.Fatal(err)
	}
	claim["signature"] = b64(ed25519.Sign(priv, canonical))
	return claim
}

func claimMap(m map[string]interface{}) map[string]interface{} { return m }

// signedParamsWithPayload mirrors signedParams but with an explicit payload.
func signedParamsWithPayload(t *testing.T, sign func([]byte) string, agentID, jobType string, caps []string, nonce string, now time.Time, payload json.RawMessage) map[string]interface{} {
	t.Helper()
	e := &security.Envelope{
		JobID:                 "job-9",
		AgentID:               agentID,
		JobType:               jobType,
		Payload:               payload,
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
	envJSON, _ := json.Marshal(e)
	var m map[string]interface{}
	_ = json.Unmarshal(envJSON, &m)
	return map[string]interface{}{"_envelope": m, "package_names": []interface{}{"nginx"}}
}
