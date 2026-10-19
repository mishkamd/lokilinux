package policy

import (
	"encoding/base64"
	"crypto/ed25519"
	"encoding/json"
	"strings"
	"testing"
)

// test infrastructure — deterministic ed25519 keypair + canonical bytes
type signer struct {
	pub  ed25519.PublicKey
	priv ed25519.PrivateKey
	id   string
}

func newSigner(id string) *signer {
	pub, priv, _ := ed25519.GenerateKey(nil)
	return &signer{pub: pub, priv: priv, id: id}
}

func (s *signer) trustedKeys() map[string]string {
	return map[string]string{s.id: base64.StdEncoding.EncodeToString(s.pub)}
}

func (s *signer) signEnvelope(payload []byte, version int) Envelope {
	hash := HashOf(payload)
	sig := ed25519.Sign(s.priv, payload)
	return Envelope{
		PolicyID:     "11111111-1111-1111-1111-111111111111",
		Version:      version,
		Hash:         hash,
		SignatureB64: base64.StdEncoding.EncodeToString(sig),
		SigningKeyID: s.id,
		Payload:      payload,
	}
}

func validPayload(t *testing.T) []byte {
	t.Helper()
	doc := map[string]interface{}{
		"apiVersion": "lokilinux.io/v1",
		"kind":       "AgentPolicy",
		"metadata":   map[string]interface{}{"name": "test"},
		"spec": map[string]interface{}{
			"collectors": map[string]interface{}{
				"sshd":  map[string]interface{}{"enabled": true},
				"auditd": map[string]interface{}{"enabled": false},
			},
			"heartbeat": map[string]interface{}{"interval_seconds": 60},
			"health":    map[string]interface{}{"collect_interval_seconds": 30},
		},
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestVerify_OK(t *testing.T) {
	s := newSigner("k1")
	payload := validPayload(t)
	env := s.signEnvelope(payload, 2)

	v := NewVerifier(1) // current v1, fetching v2
	p, res, err := v.Check(payload, env, s.trustedKeys())
	if res != VerifyOK || err != nil || p == nil {
		t.Fatalf("got res=%v err=%v", res, err)
	}
	if p.Spec.Heartbeat.IntervalSeconds != 60 {
		t.Fatalf("heartbeat = %d", p.Spec.Heartbeat.IntervalSeconds)
	}
	if !p.Spec.Collectors["sshd"].Enabled {
		t.Fatal("sshd should be enabled")
	}
}

func TestVerify_TamperedPayload_Rejected(t *testing.T) {
	s := newSigner("k1")
	payload := validPayload(t)
	env := s.signEnvelope(payload, 2)

	tampered := strings.Replace(string(payload), `"interval_seconds":60`, `"interval_seconds":10`, 1)
	v := NewVerifier(1)
	if _, res, _ := v.Check([]byte(tampered), env, s.trustedKeys()); res != VerifyBadHash {
		t.Fatalf("res=%v want bad_hash", res)
	}
}

func TestVerify_UnknownSigner_Rejected(t *testing.T) {
	s := newSigner("evil-key")
	payload := validPayload(t)
	env := s.signEnvelope(payload, 2)
	trusted := newSigner("real-key").trustedKeys()

	v := NewVerifier(1)
	if _, res, _ := v.Check(payload, env, trusted); res != VerifyUnknownSigner {
		t.Fatalf("res=%v want unknown_signer", res)
	}
}

func TestVerify_BadSignature_Rejected(t *testing.T) {
	s := newSigner("k1")
	payload := validPayload(t)
	env := s.signEnvelope(payload, 2)
	env.SignatureB64 = base64.StdEncoding.EncodeToString(make([]byte, 64))

	v := NewVerifier(1)
	if _, res, _ := v.Check(payload, env, s.trustedKeys()); res != VerifyBadSignature {
		t.Fatalf("res=%v want bad_signature", res)
	}
}

func TestVersion_DowngradeRejected(t *testing.T) {
	s := newSigner("k1")
	payload := validPayload(t)
	env := s.signEnvelope(payload, 1)
	v := NewVerifier(5)
	if _, res, _ := v.Check(payload, env, s.trustedKeys()); res != VerifyDowngrade {
		t.Fatalf("res=%v want downgrade", res)
	}
}

func TestVersion_Duplicate_IdempotentNoOp(t *testing.T) {
	s := newSigner("k1")
	payload := validPayload(t)
	env := s.signEnvelope(payload, 3)
	v := NewVerifier(3)
	if _, res, _ := v.Check(payload, env, s.trustedKeys()); res != VerifyDuplicate {
		t.Fatalf("res=%v want duplicate", res)
	}
}

func TestParse_UnknownFieldRejected(t *testing.T) {
	payload := []byte(`{
		"apiVersion": "lokilinux.io/v1", "kind": "AgentPolicy",
		"metadata": {"name": "x"},
		"spec": {"heartbeat": {"interval_seconds": 60}},
		"sneaky": true
	}`)
	if _, err := Parse(payload); err == nil || !strings.Contains(err.Error(), "sneaky") {
		t.Fatalf("err=%v want unknown-field rejection naming sneaky", err)
	}
}

func TestParse_Faza5NonEmptyRejected(t *testing.T) {
	payload := []byte(`{
		"apiVersion": "lokilinux.io/v1", "kind": "AgentPolicy",
		"metadata": {"name": "x"},
		"spec": {"signals": {"rules": [{"id": "oom"}]}}
	}`)
	if _, err := Parse(payload); err == nil || !strings.Contains(err.Error(), "signals") {
		t.Fatalf("err=%v want signals rejection", err)
	}
}

func TestParse_ClampHeartbeatInterval(t *testing.T) {
	payload := []byte(`{
		"apiVersion": "lokilinux.io/v1", "kind": "AgentPolicy",
		"metadata": {"name": "x"},
		"spec": {"heartbeat": {"interval_seconds": 99999}}
	}`)
	p, err := Parse(payload)
	if err != nil {
		t.Fatal(err)
	}
	if p.Spec.Heartbeat.IntervalSeconds != HeartbeatIntervalMax {
		t.Fatalf("interval=%d want %d", p.Spec.Heartbeat.IntervalSeconds, HeartbeatIntervalMax)
	}
}

func TestParse_UnknownCollectorRejected(t *testing.T) {
	payload := []byte(`{
		"apiVersion": "lokilinux.io/v1", "kind": "AgentPolicy",
		"metadata": {"name": "x"},
		"spec": {"collectors": {"crypto_miner_watch": {"enabled": true}}}
	}`)
	if _, err := Parse(payload); err == nil || !strings.Contains(err.Error(), "unknown collector") {
		t.Fatalf("err=%v want unknown-collector rejection", err)
	}
}

func TestStore_CommitAtomic_LoadRoundtrip(t *testing.T) {
	dir := t.TempDir()
	store, err := NewStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	payload, meta, err := store.Load()
	if err != nil || payload != nil || meta.Version != 0 {
		t.Fatalf("first boot: payload=%v meta=%+v err=%v", payload != nil, meta, err)
	}

	payload = validPayload(t)
	staged, err := store.Stage(payload, StoredMeta{PolicyID: "p", Version: 7, Hash: HashOf(payload)})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Commit(staged); err != nil {
		t.Fatal(err)
	}

	gotPayload, gotMeta, err := store.Load()
	if err != nil {
		t.Fatal(err)
	}
	if string(gotPayload) != string(payload) || gotMeta.Version != 7 || gotMeta.Hash != HashOf(payload) {
		t.Fatalf("roundtrip mismatch: meta=%+v", gotMeta)
	}
	if store.CurrentVersion() != 7 {
		t.Fatalf("current=%d want 7", store.CurrentVersion())
	}
}

func TestHashOf_StableAndBoundToContent(t *testing.T) {
	a := []byte("same")
	b := []byte("same")
	c := []byte("different")
	if HashOf(a) != HashOf(b) || HashOf(a) == HashOf(c) {
		t.Fatal("hash not deterministic/content-bound")
	}
}
