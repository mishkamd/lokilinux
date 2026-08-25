// Package security implements the agent-side half of the signed-job trust
// model: envelope parsing, Ed25519 signature verification (verify-only — the
// private signing key never leaves the control plane), validity-window and
// identity checks, and persistent replay protection.
//
// Canonical form contract (must stay byte-identical with backend
// services/job_signing.py): the signature covers the compact JSON encoding
// of the envelope WITHOUT its Signature field, object keys sorted
// recursively. Numbers in signed payloads must be integers — float
// formatting differs between Go and Python and would break verification.
package security

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"time"
)

// Envelope is the signed job wrapper delivered inside job parameters under
// the "_envelope" key. Field names match the backend signer exactly.
// NO omitempty anywhere: the canonical bytes must contain every field on
// both sides (Go emits struct order first, but canonicalJSON re-encodes via
// sorted maps, while the Python signer sorts keys — the intersection is
// "all fields present, alphabetically sorted"). Optional fields are
// normalized to their zero value ("", {}, []) by UnsignedBytes.
type Envelope struct {
	JobID                 string          `json:"job_id"`
	AgentID               string          `json:"agent_id"`
	TenantID              string          `json:"tenant_id"`
	JobType               string          `json:"job_type"`
	Payload               json.RawMessage `json:"payload"`
	PolicyID              string          `json:"policy_id"`
	IssuedAt              int64           `json:"issued_at"`  // unix seconds
	ExpiresAt             int64           `json:"expires_at"` // unix seconds
	Nonce                 string          `json:"nonce"`
	RiskLevel             string          `json:"risk_level"` // LOW|MEDIUM|HIGH|CRITICAL
	RequestedCapabilities []string        `json:"requested_capabilities"`
	KeyVersion            *int            `json:"key_version,omitempty"` // absent = v1 (legacy envelopes stay byte-identical)
	Signature             string          `json:"signature"`             // base64(ed25519 sig)
}

// UnsignedBytes returns the exact byte sequence signatures cover: compact
// JSON of the envelope minus Signature, keys sorted recursively, optional
// fields normalized so both implementations emit identical bytes.
func (e *Envelope) UnsignedBytes() ([]byte, error) {
	cp := *e
	cp.Signature = ""
	if len(cp.Payload) == 0 {
		cp.Payload = json.RawMessage(`{}`)
	}
	if cp.RequestedCapabilities == nil {
		cp.RequestedCapabilities = []string{}
	}
	b, err := json.Marshal(&cp)
	if err != nil {
		return nil, err
	}
	return canonicalJSON(b)
}

// canonicalJSON re-encodes JSON deterministically: decode with UseNumber
// (preserves integer literals verbatim), then re-marshal — Go's encoder
// emits map keys sorted and no whitespace.
func canonicalJSON(in []byte) ([]byte, error) {
	dec := json.NewDecoder(bytes.NewReader(in))
	dec.UseNumber()
	var v interface{}
	if err := dec.Decode(&v); err != nil {
		return nil, fmt.Errorf("canonical json decode: %w", err)
	}
	out, err := json.Marshal(v)
	if err != nil {
		return nil, fmt.Errorf("canonical json encode: %w", err)
	}
	return out, nil
}

// ParseEnvelope extracts and validates structure of the "_envelope" value
// from raw job parameters JSON.
func ParseEnvelope(raw []byte) (*Envelope, error) {
	var e Envelope
	if err := json.Unmarshal(raw, &e); err != nil {
		return nil, fmt.Errorf("envelope parse: %w", err)
	}
	if e.JobID == "" || e.AgentID == "" || e.JobType == "" ||
		e.Nonce == "" || e.IssuedAt == 0 || e.ExpiresAt == 0 ||
		e.Signature == "" {
		return nil, fmt.Errorf("envelope missing required fields")
	}
	if e.ExpiresAt <= e.IssuedAt {
		return nil, fmt.Errorf("envelope expiry not after issued_at")
	}
	return &e, nil
}

// RejectReason distinguishes rejection causes for audit logging.
type RejectReason string

const (
	RejectBadSignature RejectReason = "bad_signature"
	RejectExpired      RejectReason = "expired"
	RejectNotYetValid  RejectReason = "not_yet_valid"
	RejectWrongAgent   RejectReason = "wrong_agent"
	RejectMalformed    RejectReason = "malformed"
	RejectUnknownKey   RejectReason = "unknown_signer"
)

// ClockSkew tolerates minor host drift on the issued_at lower bound only.
const ClockSkew = 30 * time.Second

// Canonical exposes deterministic re-encoding for payload-binding checks:
// callers compare canonical(agentParams) vs canonical(envelope.Payload).
func Canonical(in []byte) ([]byte, error) {
	return canonicalJSON(in)
}

// Verifier holds ONLY platform public keys, indexed by key version
// (plan §10/§11: rotation keeps old versions verifiable, RETIRED refuses).
type Verifier struct {
	byVersion map[int]ed25519.PublicKey
	retired   map[int]bool
}

// NewVerifier builds a single-version (legacy v1) verifier.
func NewVerifier(pubBase64 string) (*Verifier, error) {
	return NewVerifierSet(map[int]string{1: pubBase64}, nil)
}

// NewVerifierSet builds a versioned verifier. retired versions reject with
// unknown_signer — signatures from a compromised-and-retired key stop trusting.
func NewVerifierSet(keys map[int]string, retired []int) (*Verifier, error) {
	m := make(map[int]ed25519.PublicKey, len(keys))
	for v, b64 := range keys {
		raw, err := base64.StdEncoding.DecodeString(b64)
		if err != nil || len(raw) != ed25519.PublicKeySize {
			return nil, fmt.Errorf("invalid platform signing public key (v%d)", v)
		}
		m[v] = ed25519.PublicKey(raw)
	}
	if len(m) == 0 {
		return nil, fmt.Errorf("empty signing key set")
	}
	r := make(map[int]bool, len(retired))
	for _, v := range retired {
		r[v] = true
	}
	return &Verifier{byVersion: m, retired: r}, nil
}

// Public returns the raw Ed25519 public key (for callers verifying
// non-envelope artifacts, e.g. plugin signatures).
func (v *Verifier) Public() ed25519.PublicKey {
	if v == nil {
		return nil
	}
	return v.byVersion[1]
}

// Verify checks structure, the validity window, target identity and finally
// the Ed25519 signature over the canonical unsigned bytes. expectedAgentID
// may be empty only in tests; production always supplies it.
func (v *Verifier) Verify(e *Envelope, expectedAgentID string, now time.Time) (RejectReason, error) {
	if v == nil || len(v.byVersion) == 0 {
		return RejectBadSignature, fmt.Errorf("no signing key configured")
	}
	version := 1
	if e.KeyVersion != nil {
		version = *e.KeyVersion
	}
	pub, known := v.byVersion[version]
	if !known {
		return RejectUnknownKey, fmt.Errorf("no signing key for version %d", version)
	}
	if v.retired[version] {
		return RejectUnknownKey, fmt.Errorf("signing key version %d is retired", version)
	}
	if now.Unix() > e.ExpiresAt {
		return RejectExpired, fmt.Errorf("envelope expired at %d", e.ExpiresAt)
	}
	if now.Unix()+int64(ClockSkew.Seconds()) < e.IssuedAt {
		return RejectNotYetValid, fmt.Errorf("issued_at %d too far in the future", e.IssuedAt)
	}
	if expectedAgentID != "" && e.AgentID != expectedAgentID {
		return RejectWrongAgent, fmt.Errorf("envelope targets %q, this agent is %q", e.AgentID, expectedAgentID)
	}
	unsigned, err := e.UnsignedBytes()
	if err != nil {
		return RejectMalformed, err
	}
	sig, err := base64.StdEncoding.DecodeString(e.Signature)
	if err != nil || len(sig) != ed25519.SignatureSize {
		return RejectBadSignature, fmt.Errorf("malformed signature")
	}
	if !ed25519.Verify(pub, unsigned, sig) {
		return RejectBadSignature, fmt.Errorf("signature verification failed")
	}
	return "", nil
}
