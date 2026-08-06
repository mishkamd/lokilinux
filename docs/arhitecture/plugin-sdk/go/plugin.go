// Package plugin provides the base interface and runtime context for
// LokiLinux plugins written in Go.
//
// Usage:
//
//	type MyPlugin struct{ ctx plugin.Context }
//
//	func (p *MyPlugin) Check() bool              { return true }
//	func (p *MyPlugin) Collect() (map[string]any, error) { return map[string]any{"ok": true}, nil }
//	func (p *MyPlugin) OnInstall() error         { return nil }
//	func (p *MyPlugin) OnUninstall() error       { return nil }
//
//	// Loader entry point — must be exported as "New".
//	func New(ctx plugin.Context) plugin.Plugin { return &MyPlugin{ctx: ctx} }
package plugin

import (
	"encoding/json"
	"fmt"
	"os"
)

// Context is injected by the agent sandbox at runtime.
type Context struct {
	PluginID string
	AgentID  string
	Config   map[string]string
}

// Log writes a structured log line to stderr (captured by the agent).
func (c *Context) Log(level, message string) {
	fmt.Fprintf(os.Stderr, "[%s] plugin=%s %s\n", level, c.PluginID, message)
}

// EmitMetric writes a metric event to stdout for the agent to forward.
func (c *Context) EmitMetric(name string, value float64, labels map[string]string) {
	data, _ := json.Marshal(map[string]any{
		"type": "metric", "name": name, "value": value, "labels": labels,
	})
	fmt.Println(string(data))
}

// EmitAlert writes an alert event to stdout for the agent to forward.
func (c *Context) EmitAlert(title, message, severity string) {
	data, _ := json.Marshal(map[string]any{
		"type": "alert", "title": title, "message": message, "severity": severity,
	})
	fmt.Println(string(data))
}

// Plugin is the interface every Go plugin must implement.
// The shared library must export a "New(ctx Context) Plugin" symbol.
type Plugin interface {
	// Check returns true if the integration target is reachable/configured.
	Check() bool
	// Collect gathers data and returns a JSON-serialisable map.
	Collect() (map[string]any, error)
	// OnInstall is called once after the plugin is installed on an agent.
	OnInstall() error
	// OnUninstall is called once before the plugin is removed from an agent.
	OnUninstall() error
}
