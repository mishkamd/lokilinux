package modules

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestInstallPlugin(t *testing.T) {
	artifact := []byte("plugin-bytes")
	sum := sha256.Sum256(artifact)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Write(artifact) //nolint:errcheck
	}))
	defer srv.Close()

	orig := PluginDir
	PluginDir = t.TempDir()
	defer func() { PluginDir = orig }()

	params := map[string]interface{}{
		"plugin_name":     "demo",
		"plugin_version":  "1.0.0",
		"download_url":    srv.URL,
		"checksum_sha256": hex.EncodeToString(sum[:]),
	}

	res := InstallPlugin(context.Background(), "job-1", params, 10)
	if res.ExitCode != 0 {
		t.Fatalf("install failed: %s", res.Error)
	}
	got, err := os.ReadFile(filepath.Join(PluginDir, "demo", "demo-1.0.0"))
	if err != nil || string(got) != string(artifact) {
		t.Fatalf("artifact not installed correctly: %v", err)
	}

	// checksum mismatch must fail and not leave the artifact behind
	params["checksum_sha256"] = "deadbeef"
	params["plugin_version"] = "2.0.0"
	res = InstallPlugin(context.Background(), "job-2", params, 10)
	if res.ExitCode == 0 {
		t.Fatal("expected checksum mismatch failure")
	}
	if _, err := os.Stat(filepath.Join(PluginDir, "demo", "demo-2.0.0")); err == nil {
		t.Fatal("corrupt artifact left behind")
	}

	// missing url must fail fast
	res = InstallPlugin(context.Background(), "job-3", map[string]interface{}{"plugin_name": "x"}, 10)
	if res.ExitCode == 0 {
		t.Fatal("expected failure on missing download_url")
	}
}
