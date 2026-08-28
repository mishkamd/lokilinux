package config

import (
	"os"

	"gopkg.in/yaml.v3"
)

// Config mirrors /etc/lokilinux/agent.yaml
type Config struct {
	Platform      PlatformConfig      `yaml:"platform"`
	Identity      IdentityConfig      `yaml:"identity"`
	Heartbeat     HeartbeatConfig     `yaml:"heartbeat"`
	Cache         CacheConfig         `yaml:"cache"`
	JobExecution  JobExecConfig       `yaml:"job_execution"`
	Security      SecurityConfig      `yaml:"security"`
	Logging       LoggingConfig       `yaml:"logging"`
	FileIntegrity FileIntegrityConfig `yaml:"file_integrity"`
	Policy        PolicyManagerConfig `yaml:"policy"`
	EventQueue    EventQueueConfig    `yaml:"event_queue"`
}

// PolicyManagerConfig wires the desired-state policy engine (plan Faza 2).
// Enabled=false (default) skips every code path — agents opt in by carrying
// a trusted signing key. TrustedKeys maps signing_key_id → base64 raw
// ed25519 public key; unlisted ids are rejected (no TOFU).
type PolicyManagerConfig struct {
	Enabled     bool            `yaml:"enabled"`
	StateDir    string          `yaml:"state_dir"` // default /var/lib/lokilinux-agent/policy
	TrustedKeys map[string]string `yaml:"trusted_keys"`
}

type PlatformConfig struct {
	// URL is kept in the YAML for loki-cli.sh (which greps it as text) but
	// the agent binary itself only dials GRPCEndpoint — never read in Go.
	URL          string `yaml:"url"`
	GRPCEndpoint string `yaml:"grpc_endpoint"`
}

type IdentityConfig struct {
	AgentID  string `yaml:"agent_id"`
	CertPath string `yaml:"cert_path"`
	KeyPath  string `yaml:"key_path"`
	CAPath   string `yaml:"ca_path"`
}

type HeartbeatConfig struct {
	IntervalSec int `yaml:"interval_sec"`
	// TimeoutSec/RetryBackoffMax removed (Faza 3.2 cleanup): the timeout was
	// never applied to the gRPC call and the backoff cap is hardcoded in
	// manager.go — the operator values were silently ignored. Re-add only
	// together with the code that honors them.
}

type CacheConfig struct {
	// Only SQLiteDB is read (storage.Open). Enabled/Path/RetentionDays had
	// no consumers — the queue purge runs on a fixed window instead of a
	// configured retention.
	SQLiteDB string `yaml:"sqlite_db"`
}

type JobExecConfig struct {
	// MaxParallelJobs/SandboxEnabled removed (Faza 3.2): jobs run unbounded
	// goroutines on the in-process systemd-run path — both fields were
	// decorative. TimeoutSeconds is the one wired knob.
	TimeoutSeconds int `yaml:"timeout_seconds"`
}

// SecurityConfig gates the signed-job trust model. EnforceSignedJobs starts
// false fleet-wide (staged rollout): false = accept unsigned privileged jobs
// with a WARN per job, true = reject anything without a valid Ed25519
// envelope. The signing public key arrives at enrollment via
// /agent/signing-key; without it, enforcement cannot be enabled.
type SecurityConfig struct {
	EnforceSignedJobs bool   `yaml:"enforce_signed_jobs"`
	SigningPubKeyPath string `yaml:"signing_pub_key_path"`
	// Versioned trust set for key rotation (plan §11): {"1": "<base64 pub>"}.
	// The legacy SigningPubKeyPath is folded in as version 1 when present.
	SigningPubKeys map[int]string `yaml:"signing_pub_keys"`
	RetiredKeys    []int          `yaml:"retired_key_versions"`
	// ExecBrokerSocket: when set, privileged job execution is delegated to
	// loki-agent-exec over this unix socket (non-root core mode). Empty =
	// legacy in-process systemd-run path.
	ExecBrokerSocket string `yaml:"exec_broker_socket"`
}

type LoggingConfig struct {
	// Output removed (Faza 3.2): logs always go to the systemd journal —
	// the field was never read.
	Level string `yaml:"level"`
}

// FileIntegrityConfig lets an operator override the compiled-in FIM watch
// list (agent/internal/compliance/file_integrity_collector.go's
// fileIntegrityWatchPaths) without a rebuild — docs/compliance §11's
// "monitor"/"ignore" lists, applied agent-side. Both empty means "use the
// built-in default watch list, no ignores" (compliance.BuildRegistry).
type FileIntegrityConfig struct {
	WatchPaths []string `yaml:"watch_paths"`
	Ignores    []string `yaml:"ignore_paths"`
}

// EventQueueConfig tunes internal/eq's bounded priority queue + flusher
// (Phase G2). Zero values fall back to internal/eq's own defaults (10k
// capacity, 100 events / 256KB / 1s flush triggers) — every field here is
// an override, not a required setting.
type EventQueueConfig struct {
	Enabled          bool `yaml:"enabled"`
	Capacity         int  `yaml:"capacity"`
	FlushMaxEvents   int  `yaml:"flush_max_events"`
	FlushMaxBytes    int  `yaml:"flush_max_bytes"`
	FlushIntervalSec int  `yaml:"flush_interval_sec"`
}

// Load reads and parses the YAML config file at path.
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}
	applyDefaults(&cfg)
	return &cfg, nil
}

func applyDefaults(cfg *Config) {
	if cfg.Heartbeat.IntervalSec == 0 {
		cfg.Heartbeat.IntervalSec = 60
	}
	if cfg.Cache.SQLiteDB == "" {
		cfg.Cache.SQLiteDB = "/var/lib/lokilinux/agent.db"
	}
	if cfg.JobExecution.TimeoutSeconds == 0 {
		cfg.JobExecution.TimeoutSeconds = 3600
	}
	if cfg.Security.SigningPubKeyPath == "" {
		cfg.Security.SigningPubKeyPath = "/etc/lokilinux/signing_pub.b64"
	}
	if cfg.Logging.Level == "" {
		cfg.Logging.Level = "info"
	}
}
