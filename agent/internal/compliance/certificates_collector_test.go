package compliance

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"testing"
	"time"
)

func generateTestCertPEM(t *testing.T) []byte {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("generating key: %v", err)
	}
	template := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "test.example.com"},
		NotBefore:    time.Now(),
		NotAfter:     time.Now().Add(24 * time.Hour),
		DNSNames:     []string{"test.example.com"},
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("creating certificate: %v", err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
}

func TestParseCertificatePEM_Valid(t *testing.T) {
	raw := generateTestCertPEM(t)
	facts, ok := parseCertificatePEM(raw)
	if !ok {
		t.Fatal("parseCertificatePEM returned ok=false for a valid cert")
	}
	if len(facts.DNSNames) != 1 || facts.DNSNames[0] != "test.example.com" {
		t.Errorf("DNSNames = %v, want [test.example.com]", facts.DNSNames)
	}
	if facts.NotAfter == "" {
		t.Error("NotAfter is empty")
	}
}

func TestParseCertificatePEM_NotACertificate(t *testing.T) {
	_, ok := parseCertificatePEM([]byte("not a pem block at all"))
	if ok {
		t.Error("expected ok=false for non-PEM data")
	}
}

func TestCertificatesCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*CertificatesCollector)(nil)
	c := NewCertificatesCollector()
	if c.Domain() != "certificates" {
		t.Errorf("Domain() = %q, want certificates", c.Domain())
	}
}
