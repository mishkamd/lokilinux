// Policy cache maintenance: ingest update_policy payloads from heartbeat
// responses, persist the last-good document to SQLite, serve it to the
// validation pipeline.
package agent

import (
	"context"
	"time"

	"github.com/lokilinux/agent/internal/security"
)

const localPolicyKey = "security.local_policy"

// maybeUpdatePolicy ingests resp["policy"] (plain map thanks to the gRPC
// client's structpb→map conversion). A parse failure keeps the previous good
// policy — a malformed push must never widen or blank enforcement.
func (m *Manager) maybeUpdatePolicy(resp map[string]interface{}) {
	raw, ok := resp["policy"]
	if !ok || raw == nil {
		return
	}
	lp, err := security.ParseLocalPolicy(raw, time.Now())
	if err != nil {
		m.log.Warn("ignoring unparseable policy push", "error", err)
		return
	}
	blob, err := lp.Marshal()
	if err == nil {
		if err := m.store.SetConfig(context.Background(), localPolicyKey, string(blob)); err != nil {
			m.log.Warn("policy persist failed (in-memory copy still active)", "error", err)
		}
	}
	m.policyMu.Lock()
	m.policy = lp
	m.policyMu.Unlock()
	m.log.Info("local policy updated", "version", lp.Version, "capabilities", len(lp.Capabilities))
}

// currentPolicy returns the cached policy snapshot (nil-safe).
func (m *Manager) currentPolicy() *security.LocalPolicy {
	m.policyMu.RLock()
	defer m.policyMu.RUnlock()
	return m.policy
}

// pluginVerifier returns the platform key verifier only in enforcement mode:
// unsigned plugins are rejected when enforce_signed_jobs=true, tolerated
// (checksum-only) during staged rollout.
func (m *Manager) pluginVerifier() *security.Verifier {
	if !m.secCfg.EnforceSignedJobs {
		return nil
	}
	return m.verifier
}
