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

// TestLoad_MissingFile ensures a missing config path surfaces as an error,
// not a zero-value Config silently used with wrong defaults.
func TestLoad_MissingFile(t *testing.T) {
	_, err := Load("/nonexistent/compliance.yaml")
	if err == nil {
		t.Fatal("expected an error for a missing config file")
	}
}
