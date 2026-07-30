// Package compliance implements the agent-side collectors for the
// Infrastructure Compliance & Drift Management module. Collectors are
// compiled into the binary (not dynamically loaded like the third-party
// plugin SDK in docs/plugin-sdk/) — see docs/compliance/03-AGENT-PLUGIN-SDK.md
// §1 for why the two systems are deliberately separate: these read
// security-sensitive system state on every managed server with zero install
// step, at a cadence the sandboxed third-party plugin model isn't built for.
package compliance

import (
	"context"
	"time"
)

// Facts is the canonical, normalized document one Collector produces for
// its domain. Content-addressable storage and delta-sync both depend on
// this being deterministically hashable — see Canonicalize.
type Facts map[string]any

// Collector is implemented by every built-in compliance domain collector.
type Collector interface {
	// Domain is the stable key used everywhere downstream: inventory_snapshots.domain,
	// baseline expected_state keys, rule_evaluations.domain. Never renamed once shipped.
	Domain() string

	// Collect gathers and normalizes this domain's current state.
	Collect(ctx context.Context) (Facts, error)

	// Interval overrides the default heartbeat-driven cadence for expensive
	// collectors. Zero means "every heartbeat".
	Interval() time.Duration
}

// Registry is the compile-time list of collectors this agent binary ships.
//
// ponytail: a plain slice, not a runtime-discovered registry — nothing in
// this module needs collectors added without a rebuild yet (see
// docs/compliance/03-AGENT-PLUGIN-SDK.md §2). Wiring this into the
// heartbeat loop (agent/internal/agent/manager.go) is a separate task —
// this package stays additive/standalone until that integration lands, so
// existing heartbeat behavior is never at risk from work-in-progress here.
var Registry = []Collector{
	NewSSHDCollector(),
	NewSysctlCollector(),
	NewUsersCollector(),
	NewMountsCollector(),
	NewSudoCollector(),
	NewPAMCollector(),
	NewAuditdCollector(),
	NewFirewallCollector(),
	NewSELinuxCollector(),
	NewKernelCollector(),
	NewLoginDefsCollector(),
	NewPasswordPolicyCollector(),
	NewCronCollector(),
	NewSystemdServicesCollector(),
	NewNetworkCollector(),
	NewTimeSyncCollector(),
	NewKernelModulesCollector(),
	NewOpenPortsCollector(),
	NewProcessesCollector(),
	NewCapabilitiesCollector(),
	NewCertificatesCollector(),
	NewRepositoriesCollector(),
	NewContainerRuntimeCollector(),
	NewFileIntegrityCollector(),
}
