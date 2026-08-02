package ingest

import (
	"testing"
)

func TestParseSnapshotMessage_ValidPayload(t *testing.T) {
	data := []byte(`{"agent_id":"33333333-3333-3333-3333-333333333333","domain":"sshd","content_hash":"abc123","facts":{"PermitRootLogin":"no"}}`)

	snap, err := parseSnapshotMessage(data)
	if err != nil {
		t.Fatalf("parseSnapshotMessage() error = %v", err)
	}
	if snap.AgentID.String() != "33333333-3333-3333-3333-333333333333" {
		t.Errorf("AgentID = %s, want the parsed UUID", snap.AgentID)
	}
	if snap.Domain != "sshd" {
		t.Errorf("Domain = %q, want sshd", snap.Domain)
	}
	if snap.ContentHash != "abc123" {
		t.Errorf("ContentHash = %q, want abc123", snap.ContentHash)
	}
	if snap.Facts["PermitRootLogin"] != "no" {
		t.Errorf("Facts[PermitRootLogin] = %v, want no", snap.Facts["PermitRootLogin"])
	}
}

func TestParseSnapshotMessage_InvalidJSON(t *testing.T) {
	_, err := parseSnapshotMessage([]byte(`not json`))
	if err == nil {
		t.Fatal("expected an error for invalid JSON, got nil")
	}
}

func TestParseSnapshotMessage_InvalidAgentID(t *testing.T) {
	data := []byte(`{"agent_id":"not-a-uuid","domain":"sshd","content_hash":"x","facts":{}}`)
	_, err := parseSnapshotMessage(data)
	if err == nil {
		t.Fatal("expected an error for a non-UUID agent_id, got nil")
	}
}

func TestParseSnapshotMessage_MissingFacts(t *testing.T) {
	data := []byte(`{"agent_id":"33333333-3333-3333-3333-333333333333","domain":"sshd","content_hash":"x"}`)
	snap, err := parseSnapshotMessage(data)
	if err != nil {
		t.Fatalf("parseSnapshotMessage() error = %v", err)
	}
	if snap.Facts != nil {
		t.Errorf("Facts = %v, want nil when the message omits it", snap.Facts)
	}
}
