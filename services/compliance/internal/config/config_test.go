package config

import (
	"os"
	"path/filepath"
	"testing"
)

// TestLoad_AppliesDefaults locks the default values every field falls back
// to when the YAML config omits them — mirrors agent/internal/config's
// applyDefaults convention, including "unknown keys don't error" forward
// compatibility.
func TestLoad_AppliesDefaults(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "compliance.yaml")
	if err := os.WriteFile(path, []byte("logging:\n  level: debug\n"), 0o600); err != nil {
		t.Fatalf("failed to write test config: %v", err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if cfg.Logging.Level != "debug" {
		t.Errorf("Logging.Level = %q, want %q (explicit value should not be overridden)", cfg.Logging.Level, "debug")
	}
	if cfg.NATS.URL != "nats://nats:4222" {
		t.Errorf("NATS.URL = %q, want default", cfg.NATS.URL)
	}
	if cfg.NATS.StreamName != "COMPLIANCE" {
		t.Errorf("NATS.StreamName = %q, want default COMPLIANCE", cfg.NATS.StreamName)
	}
	if cfg.NATS.MaxAckPending != 1000 {
		t.Errorf("NATS.MaxAckPending = %d, want default 1000", cfg.NATS.MaxAckPending)
	}
	if cfg.Telemetry.HealthPort != 8080 {
		t.Errorf("Telemetry.HealthPort = %d, want default 8080", cfg.Telemetry.HealthPort)
	}
	if cfg.Telemetry.MetricsPort != 9091 {
		t.Errorf("Telemetry.MetricsPort = %d, want default 9091", cfg.Telemetry.MetricsPort)
	}
	if cfg.Database.MaxOpenConns != 20 {
		t.Errorf("Database.MaxOpenConns = %d, want default 20", cfg.Database.MaxOpenConns)
	}
}

// TestLoad_MissingFileFallsBackToDefaults — the docker-compose deployment
// never mounts a compliance.yaml at all (env vars + defaults only, see
// docker-compose.yml's lokilinux-compliance service), so a missing file
// must not be fatal. Confirmed against the real deployment: this exact gap
// crash-looped the container on first-ever docker-compose up.
func TestLoad_MissingFileFallsBackToDefaults(t *testing.T) {
	cfg, err := Load("/nonexistent/compliance.yaml")
	if err != nil {
		t.Fatalf("Load with a missing file returned an error, want defaults: %v", err)
	}
	if cfg.NATS.URL != "nats://nats:4222" {
		t.Errorf("NATS.URL = %q, want default", cfg.NATS.URL)
	}
	if cfg.Telemetry.HealthPort != 8080 {
		t.Errorf("Telemetry.HealthPort = %d, want default 8080", cfg.Telemetry.HealthPort)
	}
}

// TestLoad_MalformedFileStillErrors — a file that exists but fails to parse
// is a real misconfiguration, unlike an absent optional file, and must
// still fail loudly.
func TestLoad_MalformedFileStillErrors(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "compliance.yaml")
	if err := os.WriteFile(path, []byte("not: valid: yaml: [structure"), 0o600); err != nil {
		t.Fatalf("failed to write test config: %v", err)
	}

	if _, err := Load(path); err == nil {
		t.Fatal("expected an error for a malformed config file")
	}
}
