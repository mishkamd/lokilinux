package security

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"testing"
	"time"
)

// testKey is generated per-run; fixtures that must match the backend signer
// live in envelope_crosslang_test.go (P2.1).
func newTestSigner(t *testing.T) (pubB64 string, sign func(unsigned []byte) string) {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	return base64.StdEncoding.EncodeToString(pub),
		func(unsigned []byte) string {
			return base64.StdEncoding.EncodeToString(ed25519.Sign(priv, unsigned))
		}
}

func validEnvelope(sign func([]byte) string) *Envelope {
	e := &Envelope{
		JobID:     "job-1",
		AgentID:   "agent-1",
		TenantID:  "tenant-1",
		JobType:   "SERVICE",
		Payload:   json.RawMessage(`{"service_name":"nginx","action":"restart"}`),
		IssuedAt:  time.Now().Add(-time.Minute).Unix(),
		ExpiresAt: time.Now().Add(5 * time.Minute).Unix(),
		Nonce:     "nonce-abc",
		RiskLevel: "MEDIUM",
		RequestedCapabilities: []string{"SERVICE_CONTROL"},
	}
	unsigned, err := e.UnsignedBytes()
	if err != nil {
		panic(err)
	}
	e.Signature = sign(unsigned)
	return e
}

func TestVerifyAcceptsWellFormed(t *testing.T) {
	pubB64, sign := newTestSigner(t)
	v, err := NewVerifier(pubB64)
	if err != nil {
		t.Fatal(err)
	}
	e := validEnvelope(sign)
	if reason, err := v.Verify(e, "agent-1", time.Now()); err != nil {
		t.Fatalf("reason=%q unexpected error: %v", reason, err)
	}
}

func TestVerifyRejectsTamperedPayload(t *testing.T) {
	pubB64, sign := newTestSigner(t)
	v, _ := NewVerifier(pubB64)
	e := validEnvelope(sign)
	e.Payload = json.RawMessage(`{"service_name":"sshd","action":"stop"}`)
	if _, err := v.Verify(e, "agent-1", time.Now()); err == nil {
		t.Fatal("tampered payload accepted")
	}
}

func TestVerifyRejectsExpired(t *testing.T) {
	pubB64, sign := newTestSigner(t)
	v, _ := NewVerifier(pubB64)
	e := validEnvelope(sign)
	e.ExpiresAt = time.Now().Add(-time.Hour).Unix()
	if reason, err := v.Verify(e, "agent-1", time.Now()); reason != RejectExpired || err == nil {
		t.Fatalf("want RejectExpired, got reason=%q err=%v", reason, err)
	}
}

func TestVerifyRejectsNotYetValid(t *testing.T) {
	pubB64, sign := newTestSigner(t)
	v, _ := NewVerifier(pubB64)
	e := validEnvelope(sign)
	e.IssuedAt = time.Now().Add(time.Hour).Unix()
	e.ExpiresAt = time.Now().Add(2 * time.Hour).Unix()
	if reason, err := v.Verify(e, "agent-1", time.Now()); reason != RejectNotYetValid || err == nil {
		t.Fatalf("want RejectNotYetValid, got reason=%q err=%v", reason, err)
	}
}

func TestVerifyRejectsWrongAgent(t *testing.T) {
	pubB64, sign := newTestSigner(t)
	v, _ := NewVerifier(pubB64)
	e := validEnvelope(sign)
	if reason, err := v.Verify(e, "agent-OTHER", time.Now()); reason != RejectWrongAgent || err == nil {
		t.Fatalf("want RejectWrongAgent, got reason=%q err=%v", reason, err)
	}
}

func TestVerifyRejectsWrongKey(t *testing.T) {
	pubB64, _ := newTestSigner(t)
	otherPub, otherSign := newTestSigner(t)
	_ = otherPub
	v, _ := NewVerifier(pubB64)
	e := validEnvelope(otherSign)
	if _, err := v.Verify(e, "agent-1", time.Now()); err == nil {
		t.Fatal("signature from a different key accepted")
	}
}

func TestParseEnvelopeRejectsIncomplete(t *testing.T) {
	raws := []string{
		`{}`,
		`{"job_id":"j"}`,
		`{"job_id":"j","agent_id":"a","job_type":"SERVICE","nonce":"n","issued_at":1,"expires_at":0,"signature":"x"}`,
		`{"job_id":"j","agent_id":"a","job_type":"SERVICE","nonce":"n","issued_at":10,"expires_at":5,"signature":"x"}`,
	}
	for _, raw := range raws {
		if _, err := ParseEnvelope([]byte(raw)); err == nil {
			t.Fatalf("accepted malformed envelope: %s", raw)
		}
	}
}

func TestCanonicalJSONStableAcrossKeyOrder(t *testing.T) {
	a := []byte(`{"b":1,"a":{"d":2,"c":3}}`)
	b := []byte(`{"a":{"c":3,"d":2},"b":1}`)
	ca, err := canonicalJSON(a)
	if err != nil {
		t.Fatal(err)
	}
	cb, err := canonicalJSON(b)
	if err != nil {
		t.Fatal(err)
	}
	if string(ca) != string(cb) {
		t.Fatalf("canonical forms differ:\n%s\n%s", ca, cb)
	}
}

func TestUnsignedBytesExcludesSignature(t *testing.T) {
	pubB64, sign := newTestSigner(t)
	v, _ := NewVerifier(pubB64)
	e := validEnvelope(sign)
	unsigned, err := e.UnsignedBytes()
	if err != nil {
		t.Fatal(err)
	}
	e.Signature = "different-signature"
	again, _ := e.UnsignedBytes()
	if string(unsigned) != string(again) {
		t.Fatal("signature field leaks into unsigned bytes")
	}
	// restored original signature still verifies over identical unsigned bytes
	e.Signature = validEnvelope(sign).Signature
	if _, err := v.Verify(e, "agent-1", time.Now()); err != nil {
		t.Fatalf("verify after restore: %v", err)
	}
}
