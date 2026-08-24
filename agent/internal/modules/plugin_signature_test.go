package modules

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/lokilinux/agent/internal/security"
)

func TestInstallPluginSignatureGate(t *testing.T) {
	pub, priv, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	goodVerifier, err := security.NewVerifier(base64.StdEncoding.EncodeToString(pub))
	if err != nil {
		t.Fatal(err)
	}
	otherPub, _, _ := ed25519.GenerateKey(nil)
	otherVerifier, err := security.NewVerifier(base64.StdEncoding.EncodeToString(otherPub))
	if err != nil {
		t.Fatal(err)
	}

	artifact := []byte("plugin-binary-v1")
	sum := sha256.Sum256(artifact)
	digest := hex.EncodeToString(sum[:])
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write(artifact)
	}))
	defer srv.Close()

	signOverDigest := func(key ed25519.PrivateKey, d string) string {
		return base64.StdEncoding.EncodeToString(ed25519.Sign(key, []byte("sha256:"+d)))
	}

	cases := []struct {
		name      string
		verifier  *security.Verifier
		paramsMod func(map[string]interface{})
		wantFail  bool
	}{
		{"valid signature accepted", goodVerifier, func(p map[string]interface{}) {
			p["signature"] = signOverDigest(priv, digest)
		}, false},
		{"missing signature rejected", goodVerifier, func(p map[string]interface{}) {}, true},
		{"garbage signature rejected", goodVerifier, func(p map[string]interface{}) {
			p["signature"] = base64.StdEncoding.EncodeToString(make([]byte, 64))
		}, true},
		{"wrong-key signature rejected", otherVerifier, func(p map[string]interface{}) {
			p["signature"] = signOverDigest(priv, digest)
		}, true},
		{"nil verifier skips check", nil, func(p map[string]interface{}) {}, false},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			orig := PluginDir
			PluginDir = dir
			defer func() { PluginDir = orig }()

			params := map[string]interface{}{
				"plugin_name":     "demo",
				"plugin_version":  "1.0.0",
				"download_url":    srv.URL,
				"checksum_sha256": digest,
			}
			tc.paramsMod(params)

			res := InstallPlugin(context.Background(), "job-x", params, 10, tc.verifier)
			if tc.wantFail && res.ExitCode == 0 {
				t.Fatalf("expected rejection, got success: %s", res.Stdout)
			}
			if !tc.wantFail && res.ExitCode != 0 {
				t.Fatalf("expected install, got: %s", res.Error)
			}
		})
	}
}
