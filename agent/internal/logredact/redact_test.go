package logredact

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"
)

func capture(t *testing.T, fn func(log *slog.Logger)) string {
	t.Helper()
	var buf bytes.Buffer
	h := slog.NewJSONHandler(&buf, &slog.HandlerOptions{Level: slog.LevelDebug})
	log := slog.New(NewHandler(h))
	fn(log)
	return buf.String()
}

func TestRedactsSensitiveTopLevelAttrs(t *testing.T) {
	out := capture(t, func(log *slog.Logger) {
		log.Info("job received", "job_id", "j1", "token", "supersecret", "PASSWORD", "hunter2")
	})
	if strings.Contains(out, "supersecret") || strings.Contains(out, "hunter2") {
		t.Fatalf("secret leaked: %s", out)
	}
	for _, want := range []string{`"token":"[REDACTED]"`, `"PASSWORD":"[REDACTED]"`, `"job_id":"j1"`} {
		if !strings.Contains(out, want) {
			t.Fatalf("missing %s in: %s", want, out)
		}
	}
}

func TestRedactsInsideGroupsAndWithAttrs(t *testing.T) {
	out := capture(t, func(log *slog.Logger) {
		base := log.With("api_key", "leak-me")
		base.Info("envelope", slog.Group("payload",
			slog.String("command", "ls"),
			slog.String("private_key", "BEGIN RSA"),
		))
	})
	if strings.Contains(out, "leak-me") || strings.Contains(out, "BEGIN RSA") {
		t.Fatalf("secret leaked: %s", out)
	}
	if !strings.Contains(out, `"command":"ls"`) {
		t.Fatalf("non-sensitive attr lost: %s", out)
	}
}

func TestBenignKeysUntouched(t *testing.T) {
	out := capture(t, func(log *slog.Logger) {
		log.Info("heartbeat", "agent_id", "a1", "session_count", 3)
	})
	// "session" is in the sensitive list but session_count must NOT match
	if !strings.Contains(out, `"session_count":3`) {
		t.Fatalf("benign attr masked: %s", out)
	}
	var rec map[string]interface{}
	if err := json.Unmarshal([]byte(out), &rec); err != nil {
		t.Fatalf("output not valid json: %v", err)
	}
}
