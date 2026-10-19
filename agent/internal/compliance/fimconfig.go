package compliance

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
)

// ErrFIMConfigDuplicate marks the common, expected case: the control plane
// re-attaches the current fim_config to every heartbeat (unlike the
// desired-state policy envelope, it isn't offer-once-until-acked), so most
// heartbeats carry a document whose version equals what's already applied.
// Callers should treat this as a silent no-op, not a warning — mirrors
// agent/internal/policy/verify.go's VerifyDuplicate.
var ErrFIMConfigDuplicate = errors.New("fim_config: version already applied")

// FIMScope is the file-integrity watch/ignore scope resolved for one agent
// — either the platform's GLOBAL default or an AGENT-specific override
// (backend/lokilinux/services/fim_scope_service.py). It travels over the
// heartbeat response as a signed envelope (see VerifyFIMConfig) separate
// from the desired-state policy envelope: policy is deny-by-default across
// all 18 collectors and only reaches agents with an explicit deployment,
// while FIM scope must reach every agent, policy or not.
type FIMScope struct {
	AgentID     string   `json:"agent_id"`
	WatchPaths  []string `json:"watch_paths"`
	IgnorePaths []string `json:"ignore_paths"`
	Version     int64    `json:"version"`
}

// fimConfigEnvelope is the wire shape: payload is the exact canonical JSON
// string that was signed (ed25519.Verify needs the precise signed bytes —
// re-serializing FIMScope ourselves could reorder or reformat and break
// verification), signature is base64 raw ed25519 over payload's bytes.
type fimConfigEnvelope struct {
	Payload      string `json:"payload"`
	SignatureB64 string `json:"signature"`
	SigningKeyID string `json:"signing_key_id"`
}

// VerifyFIMConfig checks a fim_config document fetched from the heartbeat
// response against the pinned signer, this agent's own id, and version
// monotonicity — mirroring agent/internal/policy/verify.go's pipeline
// (signer pin → signature → downgrade/duplicate → parse), minus the
// separate content-hash step: unlike the policy envelope, the signature
// here covers the payload bytes directly, so there's no independent hash to
// cross-check.
//
// trustedKeys maps signing_key_id → base64 raw ed25519 public key — the
// same PolicyManagerConfig.TrustedKeys an agent already carries for policy
// envelopes (both channels are signed with the platform's one
// "policy-signing-v1" key). No trust-on-first-use: an unlisted signing key
// id is rejected regardless of what the envelope claims.
func VerifyFIMConfig(raw []byte, selfAgentID string, trustedKeys map[string]string, lastVersion int64) (FIMScope, error) {
	var env fimConfigEnvelope
	if err := json.Unmarshal(raw, &env); err != nil {
		return FIMScope{}, fmt.Errorf("fim_config: malformed envelope: %w", err)
	}

	pubB64, pinned := trustedKeys[env.SigningKeyID]
	if !pinned {
		return FIMScope{}, fmt.Errorf("fim_config: signing key %q not in trusted_keys", env.SigningKeyID)
	}
	pub, err := base64.StdEncoding.DecodeString(pubB64)
	if err != nil || len(pub) != ed25519.PublicKeySize {
		return FIMScope{}, fmt.Errorf("fim_config: pinned key %q invalid ed25519", env.SigningKeyID)
	}
	sig, err := base64.StdEncoding.DecodeString(env.SignatureB64)
	if err != nil {
		return FIMScope{}, fmt.Errorf("fim_config: signature base64: %w", err)
	}
	if !ed25519.Verify(ed25519.PublicKey(pub), []byte(env.Payload), sig) {
		return FIMScope{}, errors.New("fim_config: ed25519 verification failed")
	}

	var scope FIMScope
	if err := json.Unmarshal([]byte(env.Payload), &scope); err != nil {
		return FIMScope{}, fmt.Errorf("fim_config: malformed payload: %w", err)
	}
	if scope.AgentID != selfAgentID {
		return FIMScope{}, fmt.Errorf("fim_config: agent_id %q does not match this agent", scope.AgentID)
	}
	if scope.Version == lastVersion {
		return FIMScope{}, ErrFIMConfigDuplicate
	}
	if scope.Version < lastVersion {
		return FIMScope{}, fmt.Errorf("fim_config: version %d < last applied %d — downgrade refused", scope.Version, lastVersion)
	}
	return scope, nil
}
