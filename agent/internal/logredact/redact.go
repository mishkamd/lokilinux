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
	"session", "bearer",
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
	masked := r.Clone()
	masked.Attrs(func(a slog.Attr) bool {
		if a.Value.Kind() == slog.KindGroup {
			maskGroup(&a)
			return true
		}
		if isSensitive(a.Key) {
			a.Value = slog.StringValue("[REDACTED]")
		}
		return true
	})
	return h.inner.Handle(ctx, masked)
}

func maskGroup(a *slog.Attr) {
	grp := a.Value.Group()
	for i := range grp {
		if grp[i].Value.Kind() == slog.KindGroup {
			maskGroup(&grp[i])
			continue
		}
		if isSensitive(grp[i].Key) {
			grp[i].Value = slog.StringValue("[REDACTED]")
		}
	}
}

func (h *redactingHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	safe := make([]slog.Attr, len(attrs))
	copy(safe, attrs)
	for i := range safe {
		if safe[i].Value.Kind() != slog.KindGroup && isSensitive(safe[i].Key) {
			safe[i].Value = slog.StringValue("[REDACTED]")
		}
	}
	return &redactingHandler{inner: h.inner.WithAttrs(safe)}
}

func (h *redactingHandler) WithGroup(name string) slog.Handler {
	return &redactingHandler{inner: h.inner.WithGroup(name)}
}
