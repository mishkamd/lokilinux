package communication

import (
	"testing"

	gen "github.com/lokilinux/agent/gen/lokilinux"
	"github.com/lokilinux/agent/internal/modules"
)

// Regression test for the bug where a server's Overview tab shows FQDN and
// Agent Version as empty: payloadToRequest must always carry a non-empty
// AgentVersion and forward SystemStatus.FQDN through untouched when the
// caller supplied non-empty values.
func TestPayloadToRequest_AgentVersionAndFQDN(t *testing.T) {
	payload := map[string]interface{}{
		"agent_id":      "agent-123",
		"agent_version": "1.2.3",
		"system": &modules.SystemInfo{
			Hostname: "web-01",
			FQDN:     "web-01.internal.example.com",
			OSFamily: "linux",
		},
	}

	req := payloadToRequest(payload)

	if req.AgentVersion != "1.2.3" {
		t.Errorf("AgentVersion = %q, want %q", req.AgentVersion, "1.2.3")
	}
	if req.SystemStatus == nil {
		t.Fatal("SystemStatus is nil")
	}
	if req.SystemStatus.FQDN != "web-01.internal.example.com" {
		t.Errorf("SystemStatus.FQDN = %q, want %q", req.SystemStatus.FQDN, "web-01.internal.example.com")
	}
	if req.SystemStatus.Hostname != "web-01" {
		t.Errorf("SystemStatus.Hostname = %q, want %q", req.SystemStatus.Hostname, "web-01")
	}
}

// Guards against a future refactor silently dropping agent_version when the
// system info block is present but the map key is missing/empty — the field
// should just stay unset, not panic or overwrite with an empty SystemStatus.
func TestPayloadToRequest_MissingAgentVersion(t *testing.T) {
	payload := map[string]interface{}{
		"agent_id": "agent-123",
		"system":   &modules.SystemInfo{Hostname: "web-02", FQDN: "web-02"},
	}

	req := payloadToRequest(payload)

	if req.AgentVersion != "" {
		t.Errorf("AgentVersion = %q, want empty when not supplied", req.AgentVersion)
	}
	if req.SystemStatus == nil || req.SystemStatus.FQDN != "web-02" {
		t.Errorf("SystemStatus.FQDN = %v, want %q", req.SystemStatus, "web-02")
	}
}

func TestPayloadToRequest_HealthAndJobResults(t *testing.T) {
	payload := map[string]interface{}{
		"agent_id": "agent-123",
		"health": modules.Health{
			CPUUsagePercent:    12.5,
			MemoryUsagePercent: 60,
			DiskUsagePercent:   80,
		},
		"job_results": []modules.JobResult{
			{JobID: "job-1", ExitCode: 0, Stdout: "ok"},
			{JobID: "job-2", ExitCode: 1, Stderr: "boom", Error: "exit status 1"},
		},
	}

	req := payloadToRequest(payload)

	if req.Health == nil || req.Health.MemoryUsage != 60 || req.Health.DiskUsage != 80 {
		t.Errorf("Health = %+v, want mem=60 disk=80", req.Health)
	}
	if len(req.JobResults) != 2 {
		t.Fatalf("JobResults len = %d, want 2", len(req.JobResults))
	}
	if req.JobResults[0].State != gen.JobCompleted {
		t.Errorf("job-1 State = %v, want JobCompleted", req.JobResults[0].State)
	}
	if req.JobResults[1].State != gen.JobFailed {
		t.Errorf("job-2 State = %v, want JobFailed", req.JobResults[1].State)
	}
	if req.JobResults[1].ErrorMessage != "exit status 1" {
		t.Errorf("job-2 ErrorMessage = %q, want %q", req.JobResults[1].ErrorMessage, "exit status 1")
	}
}

// Regression: after grpc-go leaves a ClientConn in a permanently broken
// state, Reconnect must discard it rather than reuse the same dead
// transport — this is the fix for an agent that sat in a heartbeat failure
// loop for hours because retries kept hitting the same broken connection.
func TestReconnect_ClearsStaleConnectionEvenWhenDialFails(t *testing.T) {
	c := NewGRPCClient("127.0.0.1:1", "/nonexistent/cert", "/nonexistent/key", "/nonexistent/ca")

	err := c.Reconnect()
	if err == nil {
		t.Fatal("expected Reconnect to fail with missing cert files")
	}
	if c.cc != nil {
		t.Error("cc should remain nil after a failed dial")
	}
}
