// Collector policy pull loop (Phase G2, task G2-7) — separate concern from
// policy_cache.go's security LocalPolicy update flow (that one rides the
// heartbeat response; this one is a dedicated SyncPolicy RPC pulling
// observability collector on/off/interval/threshold config). A malformed
// or failed sync retains the previous good policy — same invariant
// policy_cache.go documents for the security policy: never widen or blank
// enforcement/config on a bad push.
package agent

import (
	"context"
	"time"

	gen "github.com/lokilinux/agent/gen/lokilinux"
)

// defaultPolicySyncInterval is how often the agent pulls collector policy.
// Not currently configurable — cheap to add a config field later if an
// operator needs a different cadence; no evidence yet that they do.
const defaultPolicySyncInterval = 5 * time.Minute

// currentCollectorPolicyVersion returns the version last applied — used both
// to skip a no-op SyncPolicy response and to report policy_version on the
// next outgoing heartbeat (via the repurposed config_version field).
func (m *Manager) currentCollectorPolicyVersion() string {
	m.collectorPolicyMu.RLock()
	defer m.collectorPolicyMu.RUnlock()
	return m.collectorPolicyVersion
}

func (m *Manager) currentCollectorPolicies() map[string]gen.CollectorPolicy {
	m.collectorPolicyMu.RLock()
	defer m.collectorPolicyMu.RUnlock()
	return m.collectorPolicies
}

// syncPolicyLoop pulls collector policy on a fixed cadence until ctx is done.
func (m *Manager) syncPolicyLoop(ctx context.Context) {
	m.syncPolicyOnce(ctx)

	ticker := time.NewTicker(defaultPolicySyncInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			m.syncPolicyOnce(ctx)
		}
	}
}

func (m *Manager) syncPolicyOnce(ctx context.Context) {
	resp, err := m.client.SyncPolicy(ctx, m.cfg.Identity.AgentID, m.currentCollectorPolicyVersion())
	if err != nil {
		m.log.Warn("collector policy sync failed, retaining previous policy", "error", err)
		return
	}
	if resp == nil || resp.Version == "" || resp.Version == m.currentCollectorPolicyVersion() {
		return
	}

	m.collectorPolicyMu.Lock()
	m.collectorPolicyVersion = resp.Version
	m.collectorPolicies = resp.Collectors
	m.collectorPolicyMu.Unlock()

	m.log.Info("collector policy updated", "version", resp.Version, "collectors", len(resp.Collectors))
}
