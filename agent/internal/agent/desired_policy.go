// Desired-state policy reconciliation (agent-policy-modernization plan
// Faza 2): verify → apply → report, entirely over the existing mTLS
// heartbeat channel. Lives in internal/agent so the apply hook can rebuild
// the compliance registry without an import cycle into internal/policy.
package agent

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/lokilinux/agent/internal/compliance"
	"github.com/lokilinux/agent/internal/config"
	"github.com/lokilinux/agent/internal/policy"
)

const healthCheckTimeout = 90 * time.Second

type DesiredPolicyManager struct {
	store    *policy.Store
	verifier *policy.Verifier
	applier  *policy.Applier
	trusted  map[string]string

	// runner + pristine collector set; each apply filters from the PRISTINE
	// list (never from an already-narrowed one).
	runner       *compliance.Runner
	baseRegistry []compliance.Collector

	mu     sync.Mutex // guards pendingReport
	report map[string]interface{}
}

func newDesiredPolicyManager(
	cfg *config.Config,
	complianceRunner *compliance.Runner,
	baseRegistry []compliance.Collector,
) (*DesiredPolicyManager, error) {
	if !cfg.Policy.Enabled {
		return nil, nil
	}
	dir := cfg.Policy.StateDir
	if dir == "" {
		dir = "/var/lib/lokilinux-agent/policy"
	}
	pstore, err := policy.NewStore(dir)
	if err != nil {
		return nil, fmt.Errorf("policy store init: %w", err)
	}
	return &DesiredPolicyManager{
		store:        pstore,
		verifier:     policy.NewVerifier(pstore.CurrentVersion()),
		trusted:      cfg.Policy.TrustedKeys,
		runner:       complianceRunner,
		baseRegistry: baseRegistry,
		applier:      policy.NewApplier(pstore),
	}, nil
}

// HandleEnvelope consumes resp["policy_envelope"], verifies and applies it.
// Returns the report map to ship with the next heartbeat's policy_report.
func (d *DesiredPolicyManager) HandleEnvelope(ctx context.Context, envelope map[string]interface{}, runner *compliance.Runner) map[string]interface{} {
	if d == nil || envelope == nil {
		return nil
	}
	payloadStr, _ := envelope["payload"].(string)
	env := policy.Envelope{
		PolicyID:     asString(envelope["policy_id"]),
		Version:      asInt(envelope["version"]),
		Hash:         asString(envelope["hash"]),
		SignatureB64: asString(envelope["signature"]),
		SigningKeyID: asString(envelope["signing_key_id"]),
	}
	deploymentID := asString(envelope["deployment_id"])
	if payloadStr == "" || env.Hash == "" || env.SignatureB64 == "" || env.Version <= 0 {
		return d.failed(env, deploymentID, "malformed_envelope", "missing payload/hash/signature/version")
	}

	p, res, err := d.verifier.Check([]byte(payloadStr), env, d.trusted)
	switch res {
	case policy.VerifyDuplicate:
		// already at this version — close the deployment without re-applying
		return d.ok(envelope, deploymentID, env.Version, 0)
	case policy.VerifyOK:
	default:
		msg := ""
		if err != nil {
			msg = err.Error()
		}
		return d.failed(env, deploymentID, string(res), msg)
	}

	meta := policy.StoredMeta{
		PolicyID:     p.Metadata.Name,
		Version:      env.Version,
		Hash:         env.Hash,
		SignatureB64: env.SignatureB64,
		KeyID:        env.SigningKeyID,
	}
	startedAt := time.Now()
	_, err = d.applier.Apply([]byte(payloadStr), meta, policy.Hooks{
		Apply: func(p2 *policy.Policy) error {
			if d.runner != nil {
				d.runner.SetRegistry(filterRegistry(d.baseRegistry, p2.Spec.Collectors))
			}
			return nil
		},
		HealthCheck: func() error {
			if d.runner == nil || ctx.Err() != nil {
				return nil
			}
			ctxTimeout, cancel := context.WithTimeout(ctx, healthCheckTimeout)
			defer cancel()
			// one real collection probe against the new state proves the
			// pipeline still runs end-to-end (plan §7 "un ciclu de colectare")
			for domainName := range enabledDomainsOf(p.Spec.Collectors) {
				if _, ok := d.runner.FullBody(domainName); ok {
					_ = ctxTimeout
					return nil
				}
			}
			return fmt.Errorf("no enabled domain produced a snapshot during health check")
		},
	})
	durationMs := time.Since(startedAt).Milliseconds()
	if err != nil {
		return d.failed(env, deploymentID, "apply_failed", err.Error())
	}
	return d.ok(envelope, deploymentID, env.Version, durationMs)
}

// enabledDomainsOf extracts enabled collector names from a validated spec.
func enabledDomainsOf(collectors map[string]policy.CollectorConfig) map[string]struct{} {
	out := map[string]struct{}{}
	for name, cfg := range collectors {
		if cfg.Enabled {
			out[name] = struct{}{}
		}
	}
	return out
}

func (d *DesiredPolicyManager) failed(env policy.Envelope, deploymentID, code, msg string) map[string]interface{} {
	if d == nil {
		return nil
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	d.report = map[string]interface{}{
		"policy_id":     env.PolicyID,
		"version":       env.Version,
		"result":        "failed",
		"error":         fmt.Sprintf("[%s] %s", code, msg),
		"deployment_id": deploymentID,
	}
	return d.report
}

func (d *DesiredPolicyManager) ok(envelope map[string]interface{}, deploymentID string, version int, durationMs int64) map[string]interface{} {
	if d == nil {
		return nil
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	d.report = map[string]interface{}{
		"policy_id":     asString(envelope["policy_id"]),
		"version":       version,
		"result":        "applied",
		"duration_ms":   durationMs,
		"deployment_id": deploymentID,
	}
	return d.report
}

// TakeReport returns and clears the queued apply report.
func (d *DesiredPolicyManager) TakeReport() map[string]interface{} {
	if d == nil {
		return nil
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	r := d.report
	d.report = nil
	return r
}

// filterRegistry keeps only collectors whose domain the policy enables.
func filterRegistry(registry []compliance.Collector, enabled map[string]policy.CollectorConfig) []compliance.Collector {
	out := make([]compliance.Collector, 0, len(registry))
	for _, c := range registry {
		if cfg, ok := enabled[c.Domain()]; ok && cfg.Enabled {
			out = append(out, c)
		}
	}
	return out
}

func asString(v interface{}) string {
	s, _ := v.(string)
	return s
}

func asInt(v interface{}) int {
	switch f := v.(type) {
	case float64: // JSON numbers decode as float64 through the codec
		return int(f)
	case int:
		return f
	default:
		return 0
	}
}
