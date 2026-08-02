package compliance

import (
	"context"
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"time"
)

// certificatesDefaultPaths inventories PEM certificates under the default
// trust-store locations for both distro families.
var certificatesDefaultPaths = []string{"/etc/ssl/certs", "/etc/pki"}

// CertificatesCollector reports expiry, issuer, and SANs for every
// certificate under the default path list — exactly what a rule like "no
// certificate expires within 30 days" needs, read via crypto/x509 rather
// than shelling out to openssl. Interval is 15 minutes, not every
// heartbeat — a filesystem walk over the trust store is comparatively
// expensive and certificate expiry never changes on a 60s timescale.
type CertificatesCollector struct{}

func NewCertificatesCollector() *CertificatesCollector { return &CertificatesCollector{} }

func (c *CertificatesCollector) Domain() string { return "certificates" }

func (c *CertificatesCollector) Interval() time.Duration { return 15 * time.Minute }

// CertificateFacts is one parsed certificate.
type CertificateFacts struct {
	Path     string   `json:"path"`
	Subject  string   `json:"subject"`
	Issuer   string   `json:"issuer"`
	NotAfter string   `json:"not_after"`
	DNSNames []string `json:"dns_names,omitempty"`
}

func (c *CertificatesCollector) Collect(ctx context.Context) (Facts, error) {
	var certs []CertificateFacts
	for _, root := range certificatesDefaultPaths {
		_ = filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
			if err != nil || d.IsDir() {
				return nil // unreadable subtree or a directory entry — skip, don't abort the walk
			}
			cert, ok := parseCertificateFile(path)
			if ok {
				certs = append(certs, cert)
			}
			return nil
		})
	}
	return Facts{"certificates": certs}, nil
}

// parseCertificateFile reads one file from disk and delegates to
// parseCertificatePEM, which is the pure, testable half of this collector.
func parseCertificateFile(path string) (CertificateFacts, bool) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return CertificateFacts{}, false
	}
	cert, ok := parseCertificatePEM(raw)
	if ok {
		cert.Path = path
	}
	return cert, ok
}

// parseCertificatePEM decodes one PEM certificate block. Non-certificate
// files (private keys, non-PEM data — this path list mixes certs with
// other file types) fail decode and are silently skipped; only certs are
// compliance-relevant.
func parseCertificatePEM(raw []byte) (CertificateFacts, bool) {
	block, _ := pem.Decode(raw)
	if block == nil || block.Type != "CERTIFICATE" {
		return CertificateFacts{}, false
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return CertificateFacts{}, false
	}
	return CertificateFacts{
		Subject:  cert.Subject.String(),
		Issuer:   cert.Issuer.String(),
		NotAfter: cert.NotAfter.UTC().Format(time.RFC3339),
		DNSNames: cert.DNSNames,
	}, true
}
