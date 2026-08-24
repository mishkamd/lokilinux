// Package logredact wraps a slog.Handler so that any attribute whose key
// looks secret-bearing is emitted as [REDACTED] instead of its value.
// Defense against credential leakage through debug-level logging of request
// params, job payloads or environment dumps (plan §34).
package logredact

import (
	"context"
	"log/slog"
	"strings"
)

// sensitiveKeys are matched case-insensitively as substrings of the
// attribute key: "agent_token", "PRIVATE_KEY_PATH_VALUE" etc. all match.
var sensitiveKeys = []string{
	"password", "passwd", "secret", "token", "private_key", "privkey",
	"authorization", "cookie", "api_key", "apikey", "credential",
	"bearer", "auth",
}

func isSensitive(key string) bool {
	k := strings.ToLower(key)
	for _, s := range sensitiveKeys {
		if strings.Contains(k, s) {
			return true
		}
	}
	return false
}

type redactingHandler struct {
	inner slog.Handler
}

// NewHandler wraps inner with secret redaction. Group names are NOT treated
// as secrets themselves; only leaf attribute values are masked.
func NewHandler(inner slog.Handler) slog.Handler {
	return &redactingHandler{inner: inner}
}

func (h *redactingHandler) Enabled(ctx context.Context, l slog.Level) bool {
	return h.inner.Enabled(ctx, l)
}

func (h *redactingHandler) Handle(ctx context.Context, r slog.Record) error {
	// Attrs() hands out copies — mutating them inside the walk is lost.
	// Rebuild the record with redacted attributes instead.
	masked := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool {
		masked.AddAttrs(redactAttr(a))
		return true
	})
	return h.inner.Handle(ctx, masked)
}

func redactAttr(a slog.Attr) slog.Attr {
	if a.Value.Kind() == slog.KindGroup {
		return slog.Attr{Key: a.Key, Value: slog.GroupValue(redactGroup(a.Value.Group())...)}
	}
	if isSensitive(a.Key) {
		a.Value = slog.StringValue("[REDACTED]")
	}
	return a
}

func redactGroup(grp []slog.Attr) []slog.Attr {
	out := make([]slog.Attr, len(grp))
	for i := range grp {
		out[i] = redactAttr(grp[i])
	}
	return out
}

func (h *redactingHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	safe := make([]slog.Attr, len(attrs))
	for i := range attrs {
		safe[i] = redactAttr(attrs[i])
	}
	return &redactingHandler{inner: h.inner.WithAttrs(safe)}
}

func (h *redactingHandler) WithGroup(name string) slog.Handler {
	return &redactingHandler{inner: h.inner.WithGroup(name)}
}
