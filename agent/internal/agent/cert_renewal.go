package agent

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"os"
	"time"
)

// certRenewalThreshold: renew once the current cert has fewer than this many
// days left. // ponytail: fixed constant, promote to config if a fleet ever
// needs a different cadence — no such need exists today.
const certRenewalThreshold = 7 * 24 * time.Hour

// certExpiry reads the leaf certificate at certPath and returns its NotAfter.
func certExpiry(certPath string) (time.Time, error) {
	data, err := os.ReadFile(certPath)
	if err != nil {
		return time.Time{}, err
	}
	block, _ := pem.Decode(data)
	if block == nil {
		return time.Time{}, fmt.Errorf("cert_renewal: %s: no PEM block found", certPath)
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return time.Time{}, err
	}
	return cert.NotAfter, nil
}

// atomicWrite writes data to path via a temp file + fsync + rename, so a
// crash or a concurrent read never observes a partially-written cert/key.
// Mirrors backend/lokilinux/kms/keys.py's _write_meta (tmp+fsync+os.replace).
func atomicWrite(path string, data []byte, perm os.FileMode) error {
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, perm)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close() //nolint:errcheck
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close() //nolint:errcheck
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// maybeRenewCertificate checks the agent's current mTLS cert and, if it
// expires within certRenewalThreshold, generates a fresh keypair locally and
// asks the control plane to sign it (PKI Faza 4) — proactively, while the
// current cert is still valid, so the RenewCertificate RPC still rides on a
// genuinely authenticated connection. A fresh keypair (not a re-signed old
// one) bounds how long a silently-compromised key stays useful to an
// attacker to one renewal period.
//
// Called from sendHeartbeat right after a successful heartbeat — the
// connection is confirmed healthy at that point, the best moment to spend
// an extra RPC on it.
func (m *Manager) maybeRenewCertificate(ctx context.Context) {
	notAfter, err := certExpiry(m.cfg.Identity.CertPath)
	if err != nil {
		m.log.Warn("cert_renewal: could not read current cert expiry", "error", err)
		return
	}
	if time.Until(notAfter) > certRenewalThreshold {
		return
	}

	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		m.log.Error("cert_renewal: keygen failed", "error", err)
		return
	}
	pubDER, err := x509.MarshalPKIXPublicKey(&key.PublicKey)
	if err != nil {
		m.log.Error("cert_renewal: public key marshal failed", "error", err)
		return
	}
	pubPEM := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: pubDER})

	resp, err := m.client.RenewCertificate(ctx, m.cfg.Identity.AgentID, string(pubPEM))
	if err != nil {
		// No retry state kept here — the next heartbeat (default 60s) tries
		// again on its own, well within the 7-day threshold's margin.
		m.log.Warn("cert_renewal: renewal request failed, will retry", "error", err, "current_expiry", notAfter)
		return
	}

	keyPEM := pem.EncodeToMemory(&pem.Block{
		Type:  "RSA PRIVATE KEY",
		Bytes: x509.MarshalPKCS1PrivateKey(key),
	})
	if err := atomicWrite(m.cfg.Identity.KeyPath, keyPEM, 0o600); err != nil {
		m.log.Error("cert_renewal: failed to write new key", "error", err)
		return
	}
	if err := atomicWrite(m.cfg.Identity.CertPath, []byte(resp.CertPem), 0o644); err != nil {
		m.log.Error("cert_renewal: failed to write new cert", "error", err)
		return
	}

	// grpc-go doesn't hot-swap the client cert on a live ClientConn — the new
	// identity only takes effect on a fresh TLS handshake.
	if err := m.client.Reconnect(); err != nil {
		m.log.Error("cert_renewal: reconnect with new cert failed", "error", err)
		return
	}
	m.log.Info("cert_renewal: renewed", "not_after_unix", resp.NotAfterUnix)
}
