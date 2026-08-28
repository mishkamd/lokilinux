package agent

import (
	"context"
	"time"

	gen "github.com/lokilinux/agent/gen/lokilinux"
	"github.com/lokilinux/agent/internal/eq"
)

// eventBatchSendTimeout bounds a single ReportEvents RPC — same order of
// magnitude as the flush interval, so a stalled send doesn't pile up
// against the next flush tick.
const eventBatchSendTimeout = 10 * time.Second

// sendEventBatch gzips records and sends them over a fresh ReportEvents
// stream. Errors are logged only — the batch is already gone from the
// queue by the time Flusher hands it here (at-most-once from this layer's
// perspective), matching the same "never break host flow" policy used
// throughout the heartbeat path.
func (m *Manager) sendEventBatch(records []eq.EventRecord) error {
	gz, err := eq.GzipJSON(records)
	if err != nil {
		m.log.Warn("event batch gzip failed", "error", err, "count", len(records))
		return err
	}

	ctx, cancel := context.WithTimeout(context.Background(), eventBatchSendTimeout)
	defer cancel()

	stream, err := m.client.ReportEvents(ctx)
	if err != nil {
		m.log.Warn("event batch stream open failed", "error", err, "count", len(records))
		return err
	}
	if err := stream.Send(&gen.EventBatch{
		AgentId:    m.cfg.Identity.AgentID,
		EventsGzip: gz,
	}); err != nil {
		m.log.Warn("event batch send failed", "error", err, "count", len(records))
		return err
	}
	ack, err := stream.CloseAndRecv()
	if err != nil {
		m.log.Warn("event batch ack failed", "error", err, "count", len(records))
		return err
	}
	if !ack.Accepted {
		m.log.Warn("event batch rejected", "error", ack.ErrorMessage, "count", len(records))
	}
	return nil
}
