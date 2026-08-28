package agent

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	gen "github.com/lokilinux/agent/gen/lokilinux"
	"github.com/lokilinux/agent/internal/communication"
	"github.com/lokilinux/agent/internal/config"
	"github.com/lokilinux/agent/internal/modules"
	"github.com/lokilinux/agent/internal/security"
)

// TestNextDelay locks the heartbeat backoff curve: base interval until 3
// consecutive failures, then exponential (1x, 2x, 4x...) capped at 5 minutes.
func TestNextDelay(t *testing.T) {
	const interval = 60 * time.Second
	cases := []struct {
		failCount int
		want      time.Duration
	}{
		{0, interval},
		{2, interval},             // still under threshold
		{3, interval},             // 60s << 0 = 1x
		{4, 2 * interval},         // 2x = 120s
		{5, 4 * interval},         // 4x = 240s
		{6, maxHeartbeatBackoff},  // 8x = 480s > 300s cap
		{60, maxHeartbeatBackoff}, // huge shift must not overflow to <=0
	}
	for _, c := range cases {
		m := &Manager{failCount: c.failCount}
		if got := m.nextDelay(interval); got != c.want {
			t.Errorf("nextDelay(failCount=%d) = %v, want %v", c.failCount, got, c.want)
		}
	}
}

// TestRunJob_UnsupportedTypeReportsFailure locks the fix for a real bug: an
// unrecognized job_type with no `command` fallback used to return (zero
// JobResult, false), which the caller reads as "don't report anything" — the
// job then sat RUNNING for up to an hour until JobTimeoutWorker swept it,
// with no indication of why. A policy engine generating jobs automatically
// needs this to fail loud within one heartbeat instead.
func TestRunJob_UnsupportedTypeReportsFailure(t *testing.T) {
	m := &Manager{log: slog.New(slog.NewTextHandler(io.Discard, nil))}

	result, ok := m.runJob(context.Background(), "job-1", "CVE_SCAN", map[string]interface{}{}, 30)

	if !ok {
		t.Fatal("runJob returned ok=false — the job would be silently dropped instead of reported as failed")
	}
	if result.ExitCode == 0 {
		t.Error("ExitCode = 0, want non-zero so the job surfaces as FAILED, not COMPLETED")
	}
	if !strings.Contains(result.Error, "CVE_SCAN") {
		t.Errorf("Error = %q, want it to name the unsupported job_type", result.Error)
	}
}

func TestRunJob_AnsibleWithoutPlaybookReportsFailure(t *testing.T) {
	m := &Manager{log: slog.New(slog.NewTextHandler(io.Discard, nil))}

	result, ok := m.runJob(context.Background(), "job-2", "ANSIBLE_PLAYBOOK", map[string]interface{}{}, 30)

	if !ok {
		t.Fatal("runJob returned ok=false for a malformed ansible job — must report FAILED instead")
	}
	if result.ExitCode == 0 {
		t.Error("ExitCode = 0, want non-zero")
	}
	if !strings.Contains(result.Error, "playbook_content") {
		t.Errorf("Error = %q, want it to name the missing parameter", result.Error)
	}
}

// TestRunJob_CommandFallbackStillWorks confirms the "any job_type + a
// command param runs as shell" escape hatch (the Tier-1 primitive the
// policy engine leans on) survived the fix — only the no-command case
// changed.
func TestRunJob_CommandFallbackStillWorks(t *testing.T) {
	m := &Manager{
		log:     slog.New(slog.NewTextHandler(io.Discard, nil)),
		jobExec: modules.NewJobExecutor(),
	}

	_, ok := m.runJob(context.Background(), "job-3", "CUSTOM_COMMAND", map[string]interface{}{"command": "true"}, 5)
	if !ok {
		t.Fatal("runJob returned ok=false for a well-formed command job")
	}
}

// TestNudge_CoalescesBurst locks the non-blocking-send shape: several jobs
// finishing back to back must coalesce into a single pending wake, not one
// per job (the heartbeat loop only ever drains one per tick, and a job's
// finish goroutine must never block on the send).
func TestNudge_CoalescesBurst(t *testing.T) {
	m := &Manager{nudge: make(chan struct{}, 1)}

	send := func() {
		select {
		case m.nudge <- struct{}{}:
		default:
		}
	}

	send()
	send()
	send()

	select {
	case <-m.nudge:
	default:
		t.Fatal("nudge channel empty after 3 sends — want at least one pending wake")
	}

	select {
	case <-m.nudge:
		t.Fatal("nudge channel had a second pending item — burst did not coalesce")
	default:
	}
}

// TestPopulateAuditFields_KnownCapability locks plan P10: a job_type present
// in security.Registry gets its capability/risk stamped from that same
// registry the pre-dispatch trust gate already consults.
func TestPopulateAuditFields_KnownCapability(t *testing.T) {
	result := populateAuditFields(modules.JobResult{JobID: "job-1"}, "PACKAGE_UPDATE", nil)

	if result.Capability != security.CapPackageManagement {
		t.Fatalf("Capability = %q, want %q", result.Capability, security.CapPackageManagement)
	}
	if result.Risk != string(security.RiskHigh) {
		t.Fatalf("Risk = %q, want %q", result.Risk, security.RiskHigh)
	}
}

func TestPopulateAuditFields_UnknownJobType_LeavesFieldsEmpty(t *testing.T) {
	result := populateAuditFields(modules.JobResult{JobID: "job-1"}, "SOME_FUTURE_JOB_TYPE", nil)

	if result.Capability != "" || result.Risk != "" {
		t.Fatalf("expected empty Capability/Risk for an unregistered job_type, got %+v", result)
	}
}

func TestPopulateAuditFields_SignedEnvelope_CarriesPolicyID(t *testing.T) {
	params := map[string]interface{}{
		"_envelope": map[string]interface{}{"policy_id": "policy-abc"},
	}
	result := populateAuditFields(modules.JobResult{JobID: "job-1"}, "PACKAGE_UPDATE", params)

	if result.PolicyID != "policy-abc" {
		t.Fatalf("PolicyID = %q, want %q", result.PolicyID, "policy-abc")
	}
}

func TestPopulateAuditFields_NoEnvelope_LeavesPolicyIDEmpty(t *testing.T) {
	result := populateAuditFields(modules.JobResult{JobID: "job-1"}, "PACKAGE_UPDATE", map[string]interface{}{})

	if result.PolicyID != "" {
		t.Fatalf("PolicyID = %q, want empty (no envelope present)", result.PolicyID)
	}
}

// TestSyncPolicyOnce_RetainsPreviousOnClientError locks Phase G2's
// "malformed push never widens enforcement" invariant (same rule
// policy_cache.go documents for the unrelated security LocalPolicy): a
// failed SyncPolicy call must leave the previously-applied collector
// policy untouched. The client here dials a bogus cert path, so the RPC
// fails at dial() — a real error path, not a mock.
func TestSyncPolicyOnce_RetainsPreviousOnClientError(t *testing.T) {
	m := &Manager{
		log: slog.New(slog.NewTextHandler(io.Discard, nil)),
		cfg: &config.Config{Identity: config.IdentityConfig{AgentID: "agent-1"}},
		client: communication.NewGRPCClient(
			"127.0.0.1:0", "/nonexistent/cert.pem", "/nonexistent/key.pem", "/nonexistent/ca.pem",
		),
	}
	m.collectorPolicyVersion = "5"
	m.collectorPolicies = map[string]gen.CollectorPolicy{"cpu": {Enabled: true}}

	m.syncPolicyOnce(context.Background())

	if got := m.currentCollectorPolicyVersion(); got != "5" {
		t.Fatalf("collectorPolicyVersion = %q, want retained %q after a failed sync", got, "5")
	}
	if got := m.currentCollectorPolicies(); len(got) != 1 {
		t.Fatalf("collectorPolicies = %v, want the previous map retained", got)
	}
}

func TestCurrentCollectorPolicyVersion_DefaultsEmpty(t *testing.T) {
	m := &Manager{}
	if got := m.currentCollectorPolicyVersion(); got != "" {
		t.Fatalf("currentCollectorPolicyVersion() = %q, want empty on a fresh Manager", got)
	}
}
