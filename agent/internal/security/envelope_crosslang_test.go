package security

import (
	"encoding/base64"
	"encoding/json"
	"testing"
	"time"
)

// Cross-language fixture: envelope signed by backend services/job_signing.py
// (Ed25519, canonical JSON contract). Regenerate via the signer; if this test
// fails after a canonical-form change, BOTH implementations drifted apart.
func TestCrossLanguageVerifyPythonSignedEnvelope(t *testing.T) {
	pubB64 := "Hi9H7zhXJU3PXnIuTFCQLFAiRT2FevvOoLp7lR/hDsc="
	envJSON := "eyJqb2JfaWQiOiAiNmYxYzJhMzQtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMDAxIiwgImFnZW50X2lkIjogIjExMTExMTExLTIyMjItNDMzMy04NDQ0LTU1NTU1NTU1NTU1NSIsICJ0ZW5hbnRfaWQiOiAidGVuYW50LTEiLCAiam9iX3R5cGUiOiAiU0VSVklDRSIsICJwYXlsb2FkIjogeyJzZXJ2aWNlX25hbWUiOiAibmdpbngiLCAiYWN0aW9uIjogInJlc3RhcnQiLCAicmV0cnkiOiAzfSwgInBvbGljeV9pZCI6ICJwb2xpY3ktcHJvZC0xIiwgImlzc3VlZF9hdCI6IDE3ODAwMDAwMDAsICJleHBpcmVzX2F0IjogMTc4MDAwMDMwMCwgIm5vbmNlIjogIjlmNmIyMjI5YzRhNTRjNGNhY2ZiNjRkMjY4MWE2MTZlIiwgInJpc2tfbGV2ZWwiOiAiTUVESVVNIiwgInJlcXVlc3RlZF9jYXBhYmlsaXRpZXMiOiBbIlNFUlZJQ0VfQ09OVFJPTCJdLCAic2lnbmF0dXJlIjogIi80QjVrQXNGemErWEczbThUQTB6YTg4MHBnS0NuSkR6NTNFTzhwWWhrL29haEJsdmwxWER4ODVUVVYvL2lZcHJOOWxBU3g4dnF5Z2xFTmxLSTlqWkFnPT0ifQ=="

	v, err := NewVerifier(pubB64)
	if err != nil {
		t.Fatalf("verifier: %v", err)
	}
		raw, err := base64.StdEncoding.DecodeString(envJSON)
	if err != nil {
		t.Fatalf("fixture b64: %v", err)
	}
	e, err := ParseEnvelope(raw)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if reason, err := v.Verify(e, e.AgentID, time.Unix(1780000100, 0)); err != nil {
		t.Fatalf("python-signed envelope rejected (reason=%s): %v", reason, err)
	}

	// tamper -> reject
	e.Payload = json.RawMessage(`{"service_name":"sshd","action":"stop","retry":3}`)
	if _, err := v.Verify(e, e.AgentID, time.Unix(1780000100, 0)); err == nil {
		t.Fatal("tampered python-signed envelope accepted")
	}
}
