package modules

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/lokilinux/agent/internal/security"
)

// PluginDir is where agent-side plugin artifacts land.
// ponytail: constant matching agent packaging docs — wire into agent.yaml
// only when a deployment actually needs a different path.
var PluginDir = "/opt/lokilinux/plugins"

// InstallPlugin downloads a plugin artifact, verifies its SHA-256 checksum,
// verifies the platform Ed25519 signature over "sha256:<digest>" when a
// verifier is supplied (enforcement mode — plan P8), and places it at
// PluginDir/<name>/<name>-<version>. Returns a JobResult shaped like a shell
// job so the existing heartbeat result path reports it back unchanged.
//
// verifier semantics: non-nil ⇒ signature REQUIRED (fail closed); nil ⇒
// observability mode (checksum-only), matching enforce_signed_jobs=false.
func InstallPlugin(ctx context.Context, jobID string, params map[string]interface{}, timeoutSec int, verifier *security.Verifier) JobResult {
	start := time.Now()
	fail := func(format string, a ...interface{}) JobResult {
		return JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf(format, a...), DurationMs: msSince(start)}
	}

	name, _ := params["plugin_name"].(string)
	version, _ := params["plugin_version"].(string)
	url, _ := params["download_url"].(string)
	wantSum, _ := params["checksum_sha256"].(string)
	sigB64, _ := params["signature"].(string)
	if name == "" || url == "" {
		return fail("plugin install missing plugin_name or download_url")
	}
	// plugin_name/plugin_version end up in filepath.Join(PluginDir, ...) below —
	// reject anything that could escape PluginDir (e.g. "../../etc/systemd/system").
	if filepath.Base(name) != name {
		return fail("invalid plugin_name %q", name)
	}
	if version != "" && filepath.Base(version) != version {
		return fail("invalid plugin_version %q", version)
	}

	if timeoutSec > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, time.Duration(timeoutSec)*time.Second)
		defer cancel()
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return fail("bad download_url %q: %v", url, err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fail("download failed: %v", err)
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusOK {
		return fail("download failed: HTTP %d", resp.StatusCode)
	}

	dir := filepath.Join(PluginDir, name)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fail("mkdir %s: %v", dir, err)
	}

	// Download to a temp file in the target dir (same filesystem → atomic
	// rename), hashing as we stream so the artifact is never read twice.
	tmp, err := os.CreateTemp(dir, ".download-*")
	if err != nil {
		return fail("temp file: %v", err)
	}
	defer os.Remove(tmp.Name()) //nolint:errcheck

	h := sha256.New()
	if _, err := io.Copy(io.MultiWriter(tmp, h), resp.Body); err != nil {
		tmp.Close() //nolint:errcheck
		return fail("download interrupted: %v", err)
	}
	if err := tmp.Close(); err != nil {
		return fail("write failed: %v", err)
	}

	gotSum := hex.EncodeToString(h.Sum(nil))
	if wantSum != "" && gotSum != wantSum {
		return fail("checksum mismatch: want %s got %s", wantSum, gotSum)
	}
	if wantSum == "" {
		return fail("plugin job carries no checksum_sha256 — refusing unsigned-by-hash install")
	}

	// Ed25519 trust gate: the platform private key signs "sha256:<digest>",
	// binding the signature to this exact artifact content. SHA-256 alone
	// only detects corruption, not a malicious publisher (plan C3).
	if verifier != nil {
		if sigB64 == "" {
			return fail("plugin signature missing — enforcement mode rejects unsigned plugins")
		}
		unsigned := []byte("sha256:" + gotSum)
		sig, err := base64.StdEncoding.DecodeString(sigB64)
		if err != nil || !ed25519.Verify(verifier.Public(), unsigned, sig) {
			return fail("plugin signature verification failed")
		}
	}

	dest := filepath.Join(dir, fmt.Sprintf("%s-%s", name, version))
	if err := os.Rename(tmp.Name(), dest); err != nil {
		return fail("install failed: %v", err)
	}

	return JobResult{
		JobID:      jobID,
		ExitCode:   0,
		Stdout:     fmt.Sprintf("plugin %s v%s installed to %s (sha256 %s)", name, version, dest, gotSum),
		DurationMs: msSince(start),
	}
}
