package broker

import (
	"encoding/json"
	"net"
	"testing"
)

type memLogger struct{ events []string }

func (m *memLogger) Audit(event, jobID string, peerUID, exitCode, durationMs int) {
	m.events = append(m.events, event)
}

func serveOnce(t *testing.T, req map[string]interface{}, peerUID, allowedUID int) Response {
	t.Helper()
	client, server := net.Pipe()
	go ServeConn(server, peerUID, allowedUID, &memLogger{})
	go func() {
		b, _ := json.Marshal(req)
		_, _ = client.Write(append(b, '\n'))
	}()
	var resp Response
	if err := json.NewDecoder(client).Decode(&resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return resp
}

func TestDeniesForeignUID(t *testing.T) {
	resp := serveOnce(t, map[string]interface{}{
		"request_id": "r1", "operation": "reboot", "arguments": map[string]interface{}{},
	}, 1234, 999)
	if resp.Error == "" || resp.OK {
		t.Fatalf("foreign UID accepted: %+v", resp)
	}
}

func TestUnknownOperationRejected(t *testing.T) {
	resp := serveOnce(t, map[string]interface{}{
		"request_id": "r1", "job_id": "j", "operation": "rm_rf_slash",
		"arguments": map[string]interface{}{},
	}, 999, 999)
	if resp.OK || resp.Error == "" {
		t.Fatal("unknown operation accepted")
	}
}

func TestServiceControlActionWhitelist(t *testing.T) {
	resp := serveOnce(t, map[string]interface{}{
		"request_id": "r2", "job_id": "j",
		"operation": "service.control",
		"arguments": map[string]interface{}{"service_name": "nginx", "action": "uninstall"},
	}, 999, 999)
	if resp.OK || resp.Error == "" {
		t.Fatal("non-whitelisted action accepted")
	}
}

func TestMissingRequiredFieldsRejected(t *testing.T) {
	resp := serveOnce(t, map[string]interface{}{"request_id": "r3"}, 999, 999)
	if resp.Error == "" {
		t.Fatal("missing operation accepted")
	}
}
