package agent

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/lokilinux/agent/internal/modules"
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
