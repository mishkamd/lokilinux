package ingest

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go/jetstream"
)

// snapshotMessage is the wire envelope on lokilinux.compliance.snapshot.{domain}
// (docs/compliance/04-PROTOCOL.md §4) — published by the gRPC passthrough
// after an agent heartbeat carries a full-body domain resync.
type snapshotMessage struct {
	AgentID     string         `json:"agent_id"`
	Domain      string         `json:"domain"`
	ContentHash string         `json:"content_hash"`
	Facts       map[string]any `json:"facts"`
}

// Consumer subscribes to the compliance snapshot subject and feeds each
// message to an Ingester.
type Consumer struct {
	ingester *Ingester
	log      *slog.Logger
}

func NewConsumer(ingester *Ingester, log *slog.Logger) *Consumer {
	return &Consumer{ingester: ingester, log: log}
}

// EnsureStream creates the JetStream stream if it doesn't already exist —
// safe to call on every startup (CreateOrUpdateStream is idempotent).
func EnsureStream(ctx context.Context, js jetstream.JetStream, streamName string) (jetstream.Stream, error) {
	return js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{
		Name:      streamName,
		Subjects:  []string{"lokilinux.compliance.>"},
		Retention: jetstream.WorkQueuePolicy, // each message consumed exactly once by the ingest pool
	})
}

// Start creates (or reattaches to) a durable pull consumer and processes
// messages until ctx is cancelled. Returns once the consume loop stops —
// callers run this in its own goroutine.
func (c *Consumer) Start(ctx context.Context, stream jetstream.Stream, durableName string, maxAckPending int) error {
	consumer, err := stream.CreateOrUpdateConsumer(ctx, jetstream.ConsumerConfig{
		Durable:       durableName,
		FilterSubject: "lokilinux.compliance.snapshot.>",
		AckPolicy:     jetstream.AckExplicitPolicy,
		MaxAckPending: maxAckPending,
	})
	if err != nil {
		return fmt.Errorf("creating durable consumer %s: %w", durableName, err)
	}

	consumeCtx, err := consumer.Consume(func(msg jetstream.Msg) {
		if err := c.handle(ctx, msg); err != nil {
			c.log.Error("failed to ingest snapshot message", "subject", msg.Subject(), "error", err)
			// NAK rather than Ack: JetStream redelivers on a bad/transient
			// failure (DB hiccup) instead of silently dropping a snapshot.
			_ = msg.Nak()
			return
		}
		_ = msg.Ack()
	})
	if err != nil {
		return fmt.Errorf("starting consume loop: %w", err)
	}
	defer consumeCtx.Stop()

	<-ctx.Done()
	return nil
}

func (c *Consumer) handle(ctx context.Context, msg jetstream.Msg) error {
	snap, err := parseSnapshotMessage(msg.Data())
	if err != nil {
		return err
	}

	result, err := c.ingester.Ingest(ctx, snap)
	if err != nil {
		return err
	}

	c.log.Info("ingested snapshot",
		"agent_id", snap.AgentID, "domain", snap.Domain,
		"rules_evaluated", result.RulesEvaluated, "unchanged", result.Unchanged,
	)
	return nil
}

// parseSnapshotMessage decodes the wire envelope into a Snapshot — split
// out from handle so it's testable without a jetstream.Msg fake.
func parseSnapshotMessage(data []byte) (Snapshot, error) {
	var payload snapshotMessage
	if err := json.Unmarshal(data, &payload); err != nil {
		return Snapshot{}, fmt.Errorf("decoding snapshot message: %w", err)
	}

	agentID, err := uuid.Parse(payload.AgentID)
	if err != nil {
		return Snapshot{}, fmt.Errorf("snapshot message has invalid agent_id %q: %w", payload.AgentID, err)
	}

	return Snapshot{
		AgentID:     agentID,
		Domain:      payload.Domain,
		ContentHash: payload.ContentHash,
		Facts:       payload.Facts,
	}, nil
}
