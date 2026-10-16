package compliance

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"testing"
)

func signedFIMEnvelope(t *testing.T, pub ed25519.PublicKey, priv ed25519.PrivateKey, scope FIMScope, keyID string) []byte {
	t.Helper()
	payload, err := json.Marshal(scope)
	if err != nil {
		t.Fatal(err)
	}
	sig := ed25519.Sign(priv, payload)
	env := fimConfigEnvelope{
		Payload:      string(payload),
		SignatureB64: base64.StdEncoding.EncodeToString(sig),
		SigningKeyID: keyID,
	}
	raw, err := json.Marshal(env)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestVerifyFIMConfig_ValidSignatureAccepted(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	trusted := map[string]string{"policy-signing-v1": base64.StdEncoding.EncodeToString(pub)}
	scope := FIMScope{AgentID: "agent-1", WatchPaths: []string{"/etc", "/opt/app"}, Version: 5}
	raw := signedFIMEnvelope(t, pub, priv, scope, "policy-signing-v1")

	got, err := VerifyFIMConfig(raw, "agent-1", trusted, 0)
	if err != nil {
		t.Fatalf("VerifyFIMConfig: %v", err)
	}
	if len(got.WatchPaths) != 2 || got.WatchPaths[1] != "/opt/app" {
		t.Errorf("WatchPaths = %v, want [/etc /opt/app]", got.WatchPaths)
	}
}

func TestVerifyFIMConfig_TamperedSignatureRejected(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	trusted := map[string]string{"policy-signing-v1": base64.StdEncoding.EncodeToString(pub)}
	scope := FIMScope{AgentID: "agent-1", WatchPaths: []string{"/etc"}, Version: 1}
	raw := signedFIMEnvelope(t, pub, priv, scope, "policy-signing-v1")

	var env fimConfigEnvelope
	if err := json.Unmarshal(raw, &env); err != nil {
		t.Fatal(err)
	}
	env.Payload = `{"agent_id":"agent-1","watch_paths":["/"],"ignore_paths":[],"version":1}`
	tampered, _ := json.Marshal(env)

	if _, err := VerifyFIMConfig(tampered, "agent-1", trusted, 0); err == nil {
		t.Fatal("expected verification failure for tampered payload, got nil error")
	}
}

func TestVerifyFIMConfig_UnknownSigningKeyRejected(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	trusted := map[string]string{"some-other-key": base64.StdEncoding.EncodeToString(pub)}
	scope := FIMScope{AgentID: "agent-1", WatchPaths: []string{"/etc"}, Version: 1}
	raw := signedFIMEnvelope(t, pub, priv, scope, "policy-signing-v1")

	if _, err := VerifyFIMConfig(raw, "agent-1", trusted, 0); err == nil {
		t.Fatal("expected rejection for unpinned signing_key_id, got nil error")
	}
}

func TestVerifyFIMConfig_ForeignAgentIDRejected(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	trusted := map[string]string{"policy-signing-v1": base64.StdEncoding.EncodeToString(pub)}
	scope := FIMScope{AgentID: "agent-2", WatchPaths: []string{"/etc"}, Version: 1}
	raw := signedFIMEnvelope(t, pub, priv, scope, "policy-signing-v1")

	if _, err := VerifyFIMConfig(raw, "agent-1", trusted, 0); err == nil {
		t.Fatal("expected rejection for mismatched agent_id, got nil error")
	}
}

func TestVerifyFIMConfig_DuplicateVersionIsSilentNoOp(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	trusted := map[string]string{"policy-signing-v1": base64.StdEncoding.EncodeToString(pub)}
	scope := FIMScope{AgentID: "agent-1", WatchPaths: []string{"/etc"}, Version: 3}
	raw := signedFIMEnvelope(t, pub, priv, scope, "policy-signing-v1")

	_, err := VerifyFIMConfig(raw, "agent-1", trusted, 3)
	if !errors.Is(err, ErrFIMConfigDuplicate) {
		t.Fatalf("VerifyFIMConfig(version==lastVersion) err = %v, want ErrFIMConfigDuplicate", err)
	}
}

func TestVerifyFIMConfig_DowngradeRejected(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	trusted := map[string]string{"policy-signing-v1": base64.StdEncoding.EncodeToString(pub)}
	scope := FIMScope{AgentID: "agent-1", WatchPaths: []string{"/etc"}, Version: 3}
	raw := signedFIMEnvelope(t, pub, priv, scope, "policy-signing-v1")

	_, err := VerifyFIMConfig(raw, "agent-1", trusted, 5)
	if err == nil || errors.Is(err, ErrFIMConfigDuplicate) {
		t.Fatalf("VerifyFIMConfig(version<lastVersion) err = %v, want a non-duplicate downgrade error", err)
	}
}
