// Package baseline computes the effective baseline for an agent by merging
// every published baseline whose scope selector matches the agent's
// attributes, most-specific wins per key (docs/compliance/06-BASELINE.md §1-2).
package baseline

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/nats-io/nats.go/jetstream"
)

// publishEvent is the payload BaselineService.publish/rollback sends on
// COMPLIANCE_BASELINE_PUBLISHED (backend/lokilinux/services/baseline_service.py).
type publishEvent struct {
	BaselineID string `json:"baseline_id"`
	VersionID  string `json:"version_id"`
}

// Consumer processes COMPLIANCE_BASELINE_PUBLISHED events by recomputing
// baseline_effective fleet-wide (06-BASELINE.md §2: "Recomputed on:
// baseline publish — fleet-wide invalidation"). Recomputation is
// idempotent, so replaying the backlog after a downtime is safe — and
// desirable: agents whose baseline was published while this service was
// down converge on their next processed event.
type Consumer struct {
	resolver *Resolver
	log      *slog.Logger
}

func NewConsumer(resolver *Resolver, log *slog.Logger) *Consumer {
	return &Consumer{resolver: resolver, log: log}
}

// Start creates (or reattaches to) a durable pull consumer for
// lokilinux.compliance.baseline.published on the shared JetStream stream
// (the same one the ingest consumer reads — filtered subjects partition
// the work) and processes messages until ctx is cancelled.
func (c *Consumer) Start(ctx context.Context, stream jetstream.Stream, maxAckPending int) error {
	consumer, err := stream.CreateOrUpdateConsumer(ctx, jetstream.ConsumerConfig{
		Durable:       "compliance-baseline",
		FilterSubject: "lokilinux.compliance.baseline.published",
		AckPolicy:     jetstream.AckExplicitPolicy,
		MaxAckPending: maxAckPending,
		MaxDeliver:    5,
		BackOff:       []time.Duration{1 * time.Second, 5 * time.Second, 30 * time.Second},
	})
	if err != nil {
		return fmt.Errorf("creating baseline consumer: %w", err)
	}

	consumeCtx, err := consumer.Consume(func(msg jetstream.Msg) {
		if err := c.handle(ctx, msg); err != nil {
			c.log.Error("failed to process baseline publish event", "subject", msg.Subject(), "error", err)
			_ = msg.NakWithDelay(5 * time.Second)
			return
		}
		_ = msg.Ack()
	})
	if err != nil {
		return fmt.Errorf("starting baseline consume loop: %w", err)
	}
	defer consumeCtx.Stop()

	<-ctx.Done()
	return nil
}

func (c *Consumer) handle(ctx context.Context, msg jetstream.Msg) error {
	var ev publishEvent
	if err := json.Unmarshal(msg.Data(), &ev); err != nil {
		// A malformed event never becomes valid — Term so it doesn't pin
		// the stream on redelivery (same pattern as ingest's permanentError).
		c.log.Error("malformed baseline publish event", "error", err)
		_ = msg.Term()
		return nil
	}

	start := time.Now()
	updated, err := c.resolver.RecomputeAll(ctx)
	if err != nil {
		return err
	}
	c.log.Info("recomputed effective baselines",
		"baseline_id", ev.BaselineID,
		"version_id", ev.VersionID,
		"agents", updated,
		"duration", time.Since(start).String(),
	)
	return nil
}