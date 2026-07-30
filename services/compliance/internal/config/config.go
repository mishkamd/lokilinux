// Package config loads /etc/lokilinux/compliance.yaml, mirroring the shape
// and conventions of agent/internal/config/config.go (flat YAML struct +
// Load + applyDefaults, env-var overrides for secrets/URLs that shouldn't
// live in a checked-in config file).
package config

import (
	"os"

	"gopkg.in/yaml.v3"
)

// Config mirrors /etc/lokilinux/compliance.yaml.
type Config struct {
	Database  DatabaseConfig  `yaml:"database"`
	NATS      NATSConfig      `yaml:"nats"`
	Baseline  BaselineConfig  `yaml:"baseline"`
	Telemetry TelemetryConfig `yaml:"telemetry"`
	Logging   LoggingConfig   `yaml:"logging"`
}

type DatabaseConfig struct {
	// URL is read from the DATABASE_URL env var in practice (matches the
	// backend/agent convention of not committing connection strings to
	// disk) — this field is the fallback for local/dev runs only.
	URL          string `yaml:"url"`
	MaxOpenConns int    `yaml:"max_open_conns"`
}

type NATSConfig struct {
	URL              string `yaml:"url"`
	StreamName       string `yaml:"stream_name"`
	ConsumerDurable  string `yaml:"consumer_durable"`
	MaxAckPending    int    `yaml:"max_ack_pending"`
	LeaderKVBucket   string `yaml:"leader_kv_bucket"`
	LeaderTTLSeconds int    `yaml:"leader_ttl_seconds"`
}

type BaselineConfig struct {
	// SigningKeyPath points at the Ed25519 private key used to sign
	// published baseline versions (docs/compliance/06-BASELINE.md §3).
	// Mounted read-only, this service only — never into lokilinux-api.
	SigningKeyPath string `yaml:"signing_key_path"`
}

type TelemetryConfig struct {
	HealthPort  int `yaml:"health_port"`
	MetricsPort int `yaml:"metrics_port"`
}

type LoggingConfig struct {
	Level string `yaml:"level"`
}

// Load reads and parses the YAML config file, applying defaults for any
// zero-valued field. Unknown YAML keys are silently ignored, matching the
// agent's config loader — forward-compatible with older binaries.
//
// A missing file is not an error: every field this struct holds is either
// defaulted by applyDefaults or overridden by an env var in cmd/compliance's
// main() (DATABASE_URL, NATS_URL) — the docker-compose deployment never
// mounts a compliance.yaml at all, running on env vars + defaults alone, so
// requiring the file to exist would make that deployment unstartable. A
// malformed file that does exist is still a hard error — that's a real
// misconfiguration, not an absent optional file.
func Load(path string) (*Config, error) {
	var cfg Config
	data, err := os.ReadFile(path)
	if err != nil {
		if !os.IsNotExist(err) {
			return nil, err
		}
	} else if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}
	applyDefaults(&cfg)
	return &cfg, nil
}

func applyDefaults(cfg *Config) {
	if cfg.Database.MaxOpenConns == 0 {
		cfg.Database.MaxOpenConns = 20 // matches backend build_engine() pool_size
	}
	if cfg.NATS.URL == "" {
		cfg.NATS.URL = "nats://nats:4222"
	}
	if cfg.NATS.StreamName == "" {
		cfg.NATS.StreamName = "COMPLIANCE"
	}
	if cfg.NATS.ConsumerDurable == "" {
		cfg.NATS.ConsumerDurable = "compliance-ingest"
	}
	if cfg.NATS.MaxAckPending == 0 {
		cfg.NATS.MaxAckPending = 1000
	}
	if cfg.NATS.LeaderKVBucket == "" {
		cfg.NATS.LeaderKVBucket = "compliance-leader"
	}
	if cfg.NATS.LeaderTTLSeconds == 0 {
		cfg.NATS.LeaderTTLSeconds = 15
	}
	if cfg.Telemetry.HealthPort == 0 {
		cfg.Telemetry.HealthPort = 8080
	}
	if cfg.Telemetry.MetricsPort == 0 {
		cfg.Telemetry.MetricsPort = 9091
	}
	if cfg.Logging.Level == "" {
		cfg.Logging.Level = "info"
	}
}
