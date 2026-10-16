// Package policy implements the agent side of desired-state policy
// management (plan §7): parse → verify → validate → stage → apply → commit,
// with the last-good document always kept active on any failure.
package policy

import (
	"encoding/json"
	"fmt"
)

// Policy mirrors lokilinux.io/v1 AgentPolicy — only the fields the agent
// runtime consumes. Unknown fields in a fetched document are REJECTED by
// Parse (plan §4: strict validation), so this struct doubles as the schema.
type Policy struct {
	APIVersion string         `json:"apiVersion"`
	Kind       string         `json:"kind"`
	Metadata   PolicyMetadata `json:"metadata"`
	Spec       PolicySpec     `json:"spec"`
}

type PolicyMetadata struct {
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
}

type CollectorConfig struct {
	Enabled bool `json:"enabled"`
}

type HeartbeatConfig struct {
	IntervalSeconds int `json:"interval_seconds"`
}

type HealthConfig struct {
	CollectIntervalSeconds int `json:"collect_interval_seconds"`
}

type PolicySpec struct {
	Collectors     map[string]CollectorConfig `json:"collectors"`
	Heartbeat      HeartbeatConfig            `json:"heartbeat"`
	Health         HealthConfig               `json:"health"`
	Signals        map[string]interface{}     `json:"signals,omitempty"`  // Faza 5 — must be empty
	Services       map[string]interface{}     `json:"services,omitempty"` // Faza 5
	Logs           map[string]interface{}     `json:"logs,omitempty"`     // Faza 5
	Limits         map[string]interface{}     `json:"limits,omitempty"`   // Faza 5
	Buffer         map[string]interface{}     `json:"buffer,omitempty"`   // Faza 5
	Compliance     map[string]interface{}     `json:"compliance,omitempty"`
	Otel           map[string]interface{}     `json:"otel,omitempty"`
}

var knownCollectors = map[string]bool{
	"auditd": true, "sshd": true, "users": true, "packages": true,
	"services": true, "network": true, "sysctl": true, "processes": true,
	"time_sync": true, "file_integrity": true, "kernel": true, "cron": true,
	"docker": true, "mounts": true, "updates": true, "certificates": true,
	"dns": true, "firewall": true,
}

const (
	HeartbeatIntervalMin = 10
	HeartbeatIntervalMax = 300
	HealthIntervalMin    = 10
	HealthIntervalMax    = 3600
)

// Envelope is what travels from the control plane: versioned payload +
// integrity bindings. Version is monotonic per policy; Hash binds content.
type Envelope struct {
	PolicyID         string `json:"policy_id"`
	Version          int    `json:"version"`
	Hash             string `json:"hash"`              // sha256 hex of canonical(payload)
	SignatureB64     string `json:"signature"`         // base64 ed25519 over canonical(payload)
	SigningKeyID     string `json:"signing_key_id"`
	PublicKeyB64     string `json:"public_key_b64"`    // raw ed25519 pubkey, base64
	Payload          json.RawMessage `json:"payload"`
}

func clamp(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// Validate checks an already-unmarshalled document. Mirrors the backend
// compiler's rules (backend/lokilinux/services/agent_policy_compiler.py):
// both sides must reject the same documents or drift creates a verification
// gap the signing chain can't cover.
func validateSpec(spec *PolicySpec) error {
	for name := range spec.Collectors {
		if !knownCollectors[name] {
			return fmt.Errorf("spec.collectors: unknown collector %q", name)
		}
	}
	// unknown top-level keys were handled in Parse via Raw decode capture
	spec.Heartbeat.IntervalSeconds = clamp(spec.Heartbeat.IntervalSeconds, HeartbeatIntervalMin, HeartbeatIntervalMax)
	spec.Health.CollectIntervalSeconds = clamp(spec.Health.CollectIntervalSeconds, HealthIntervalMin, HealthIntervalMax)
	for _, section := range []string{"signals", "services", "logs", "limits", "buffer", "compliance", "otel"} {
		// Faza-5 sections must be absent or empty — enforced at parse level by
		// removing them after checking emptiness. See Parse.
		_ = section
	}
	return nil
}
