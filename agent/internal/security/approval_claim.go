package security

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
)

// ApprovalClaim mirrors services/approval_claims.py (backend). A signed
// statement binding an approval to exactly one job execution on one agent.
type ApprovalClaim struct {
	ApprovalID    string   `json:"approval_id"`
	JobID         string   `json:"job_id"`
	JobHash       string   `json:"job_hash"`
	TargetAgentID string   `json:"target_agent_id"`
	Capabilities  []string `json:"capabilities"`
	ApproverID    string   `json:"approver_id"`
	IssuedAt      int64    `json:"issued_at"`
	ExpiresAt     int64    `json:"expires_at"`
	Nonce         string   `json:"nonce"`
	KeyVersion    *int     `json:"key_version,omitempty"`
	Signature     string   `json:"signature"` // base64(ed25519)
}

// ParseApprovalClaim validates structure only — bindings and signature are
// VerifyApprovalClaim's job so audit sees the most specific reason.
func ParseApprovalClaim(raw []byte) (*ApprovalClaim, error) {
	var c ApprovalClaim
	if err := json.Unmarshal(raw, &c); err != nil {
		return nil, fmt.Errorf("claim parse: %w", err)
	}
	if c.ApprovalID == "" || c.JobID == "" || c.JobHash == "" ||
		c.Nonce == "" || c.Signature == "" || c.ExpiresAt == 0 || c.IssuedAt == 0 {
		return nil, fmt.Errorf("claim missing required fields")
	}
	return &c, nil
}

// ClaimRejectReason values mirror backend ClaimRejected reasons.
type ClaimRejectReason string

const (
	ClaimMalformed       ClaimRejectReason = "malformed"
	ClaimExpired         ClaimRejectReason = "expired"
	ClaimWrongJob        ClaimRejectReason = "wrong_job"
	ClaimModified        ClaimRejectReason = "modified"
	ClaimWrongTarget     ClaimRejectReason = "wrong_target"
	ClaimMissingCaps     ClaimRejectReason = "missing_capabilities"
	ClaimBadSignature    ClaimRejectReason = "bad_signature"
	ClaimReplayed        ClaimRejectReason = "replayed"
	ClaimUnknownSigner   ClaimRejectReason = "unknown_signer"
)

// unsignedClaimBytes returns the canonical covered bytes (claim w/o signature).
func unsignedClaimBytes(c *ApprovalClaim) ([]byte, error) {
	cp := *c
	cp.Signature = ""
	b, err := json.Marshal(&cp)
	if err != nil {
		return nil, err
	}
	return canonicalJSON(b)
}

// VerifyApprovalClaim checks expiry, bindings, replay and the Ed25519
// signature over canonical bytes. expectedPayload is the job parameters
// MINUS _envelope/_approval_claim keys (same input as payload binding).
func (v *Verifier) VerifyApprovalClaim(
	c *ApprovalClaim,
	expectedJobID, expectedJobHash, expectedTarget string,
	requiredCapabilities []string,
	replay ReplayMarker,
	now unixTime,
) error {
	version := 1
	if c.KeyVersion != nil {
		version = *c.KeyVersion
	}
	pub, known := v.byVersion[version]
	if !known || v.retired[version] {
		return fmt.Errorf(string(ClaimUnknownSigner))
	}
	if now.Unix() > c.ExpiresAt {
		return fmt.Errorf(string(ClaimExpired))
	}
	if c.JobID != expectedJobID {
		return fmt.Errorf(string(ClaimWrongJob))
	}
	if c.JobHash != expectedJobHash {
		return fmt.Errorf(string(ClaimModified))
	}
	if expectedTarget != "" && c.TargetAgentID != expectedTarget {
		return fmt.Errorf(string(ClaimWrongTarget))
	}
	have := map[string]bool{}
	for _, cp := range c.Capabilities {
		have[cp] = true
	}
	for _, need := range requiredCapabilities {
		if !have[need] {
			return fmt.Errorf("%s:%s", ClaimMissingCaps, need)
		}
	}
	if ok, err := replay.MarkSeen("claim:"+c.Nonce, c.JobID); err != nil {
		return fmt.Errorf("replay_store_error")
	} else if !ok {
		return fmt.Errorf(string(ClaimReplayed))
	}
	unsigned, err := unsignedClaimBytes(c)
	if err != nil {
		return fmt.Errorf(string(ClaimMalformed))
	}
	sig, err := base64.StdEncoding.DecodeString(c.Signature)
	if err != nil || len(sig) != ed25519.SignatureSize || !ed25519.Verify(pub, unsigned, sig) {
		return fmt.Errorf(string(ClaimBadSignature))
	}
	return nil
}

// Minimal interfaces keep this file decoupled from storage/time packages.
type ReplayMarker interface {
	MarkSeen(nonce, jobID string) (bool, error)
}
type unixTime interface{ Unix() int64 }
