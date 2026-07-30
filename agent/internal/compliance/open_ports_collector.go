package compliance

import (
	"context"
	"time"

	"github.com/lokilinux/agent/internal/modules"
)

// OpenPortsCollector reuses SystemInfoModule's existing listening-port
// scan (agent/internal/modules/system_info.go) rather than re-implementing
// /proc/net parsing — the heartbeat already collects this for the fleet
// dashboard, and a compliance rule like "no listening port outside an
// allowlist" needs the identical data, not a second parser that could
// drift from it.
type OpenPortsCollector struct{}

func NewOpenPortsCollector() *OpenPortsCollector { return &OpenPortsCollector{} }

func (c *OpenPortsCollector) Domain() string { return "open_ports" }

func (c *OpenPortsCollector) Interval() time.Duration { return 0 }

func (c *OpenPortsCollector) Collect(ctx context.Context) (Facts, error) {
	return Facts{"listening_ports": modules.ListeningPorts()}, nil
}
