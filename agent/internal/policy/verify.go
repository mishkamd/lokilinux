package policy

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
)

// VerifyResult distinguishes rejection causes for reporting to the control
// plane via lokilinux.agent.policy.failed.
type VerifyResult string

const (
	VerifyOK            VerifyResult = "ok"
	VerifyBadHash       VerifyResult = "bad_hash"
	VerifyBadSignature  VerifyResult = "bad_signature"
	VerifyUnknownSigner VerifyResult = "unknown_signer"
	VerifyDowngrade     VerifyResult = "downgrade"
	VerifyDuplicate     VerifyResult = "duplicate" // same version — idempotent no-op
)

// Verifier checks a fetched envelope against integrity bindings and local
// version monotonicity. Order matters and mirrors the plan §8 sequence:
// hash → signer pin → signature → version → schema-parse.
type Verifier struct {
	currentVersion int
}

func NewVerifier(currentVersion int) *Verifier {
	return &Verifier{currentVersion: currentVersion}
}

// HashOf returns hex sha256 over the exact payload bytes as fetched. The
// control plane canonicalizes (sort_keys, compact) before sending; the agent
// never re-serializes — any byte difference IS a content difference.
func HashOf(payloadRaw []byte) string {
	sum := sha256Sum(payloadRaw)
	return hex.EncodeToString(sum[:])
}

// Check runs the pipeline. trustedKeys maps signing_key_id → base64 raw
// ed25519 public key; an unlisted key id is rejected regardless of what the
// envelope carries (no trust-on-first-use).
func (v *Verifier) Check(payloadRaw []byte, env Envelope, trustedKeys map[string]string) (*Policy, VerifyResult, error) {
	if got := HashOf(payloadRaw); got != env.Hash {
		return nil, VerifyBadHash, fmt.Errorf("sha256 mismatch: envelope=%s computed=%s", trunc(env.Hash), trunc(got))
	}

	pubB64, pinned := trustedKeys[env.SigningKeyID]
	if !pinned {
		return nil, VerifyUnknownSigner, fmt.Errorf("signing key %q not in trusted_keys", env.SigningKeyID)
	}
	pub, err := base64.StdEncoding.DecodeString(pubB64)
	if err != nil || len(pub) != ed25519.PublicKeySize {
		return nil, VerifyUnknownSigner, fmt.Errorf("pinned key %q invalid ed25519", env.SigningKeyID)
	}
	sig, err := base64.StdEncoding.DecodeString(env.SignatureB64)
	if err != nil {
		return nil, VerifyBadSignature, fmt.Errorf("signature base64: %w", err)
	}
	if !ed25519.Verify(ed25519.PublicKey(pub), payloadRaw, sig) {
		return nil, VerifyBadSignature, errors.New("ed25519 verification failed")
	}

	if env.Version < v.currentVersion {
		return nil, VerifyDowngrade, fmt.Errorf("version %d < current %d — downgrade refused", env.Version, v.currentVersion)
	}
	if env.Version == v.currentVersion {
		return nil, VerifyDuplicate, fmt.Errorf("version %d already applied", env.Version)
	}

	p, err := Parse(payloadRaw)
	if err != nil {
		return nil, VerifyBadHash, err // validation failure surfaces with its own message
	}
	return p, VerifyOK, nil
}

func trunc(s string) string {
	if len(s) > 16 {
		return s[:16] + "…"
	}
	return s
}
