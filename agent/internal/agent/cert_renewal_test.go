package agent

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"log/slog"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/lokilinux/agent/internal/communication"
	"github.com/lokilinux/agent/internal/config"
)

var testSerialLimit = new(big.Int).Lsh(big.NewInt(1), 128)

// writeTestCert generates a self-signed cert+key pair with the given
// expiry and writes them as PEM files under dir. Returns the cert/key paths.
func writeTestCert(t *testing.T, dir string, notAfter time.Time) (certPath, keyPath string) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}
	serial, err := rand.Int(rand.Reader, testSerialLimit)
	if err != nil {
		t.Fatalf("serial: %v", err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: "test-agent"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     notAfter,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("create cert: %v", err)
	}
	certPath = filepath.Join(dir, "agent.crt")
	keyPath = filepath.Join(dir, "agent.key")
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	if err := os.WriteFile(certPath, certPEM, 0o600); err != nil {
		t.Fatalf("write cert: %v", err)
	}
	if err := os.WriteFile(keyPath, keyPEM, 0o600); err != nil {
		t.Fatalf("write key: %v", err)
	}
	return certPath, keyPath
}

func TestCertExpiry(t *testing.T) {
	dir := t.TempDir()
	want := time.Now().Add(45 * 24 * time.Hour).Truncate(time.Second)
	certPath, _ := writeTestCert(t, dir, want)

	got, err := certExpiry(certPath)
	if err != nil {
		t.Fatalf("certExpiry: %v", err)
	}
	if !got.Truncate(time.Second).Equal(want.UTC().Truncate(time.Second)) {
		t.Errorf("certExpiry = %v, want %v", got, want)
	}
}

func TestCertExpiry_MissingFile(t *testing.T) {
	if _, err := certExpiry(filepath.Join(t.TempDir(), "does-not-exist.crt")); err == nil {
		t.Fatal("expected error for missing cert file")
	}
}

func TestAtomicWrite(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "agent.key")

	if err := atomicWrite(path, []byte("first"), 0o600); err != nil {
		t.Fatalf("atomicWrite: %v", err)
	}
	if err := atomicWrite(path, []byte("second"), 0o600); err != nil {
		t.Fatalf("atomicWrite overwrite: %v", err)
	}

	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(got) != "second" {
		t.Errorf("content = %q, want %q", got, "second")
	}
	if _, err := os.Stat(path + ".tmp"); !os.IsNotExist(err) {
		t.Errorf("temp file %s.tmp should not survive a successful write", path)
	}
}

func TestMaybeRenewCertificate_NotNearExpiry_LeavesFilesUntouched(t *testing.T) {
	dir := t.TempDir()
	certPath, keyPath := writeTestCert(t, dir, time.Now().Add(60*24*time.Hour))
	before, _ := os.ReadFile(certPath)

	m := &Manager{
		cfg: &config.Config{Identity: config.IdentityConfig{
			AgentID: "test-agent", CertPath: certPath, KeyPath: keyPath,
		}},
		log: slog.Default(),
		// client left nil on purpose: if the threshold gate is wrong and this
		// path gets reached anyway, RenewCertificate on a nil *GRPCClient
		// panics — a louder failure than a passed assertion would be.
	}

	m.maybeRenewCertificate(context.Background())

	after, _ := os.ReadFile(certPath)
	if string(before) != string(after) {
		t.Error("cert file was modified even though it wasn't near expiry")
	}
}

func TestMaybeRenewCertificate_NearExpiry_RenewalFailureLeavesFilesUntouched(t *testing.T) {
	dir := t.TempDir()
	certPath, keyPath := writeTestCert(t, dir, time.Now().Add(2*24*time.Hour))
	before, _ := os.ReadFile(certPath)

	// Points at a real cert/key (so dial() succeeds locally) but an address
	// nothing listens on — the RPC itself fails, exercising the "renewal
	// request failed" path without a fake server.
	client := communication.NewGRPCClient("127.0.0.1:1", certPath, keyPath, certPath)
	m := &Manager{
		cfg: &config.Config{Identity: config.IdentityConfig{
			AgentID: "test-agent", CertPath: certPath, KeyPath: keyPath,
		}},
		log:    slog.Default(),
		client: client,
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	m.maybeRenewCertificate(ctx)

	after, _ := os.ReadFile(certPath)
	if string(before) != string(after) {
		t.Error("cert file was modified despite the renewal RPC failing")
	}
}
