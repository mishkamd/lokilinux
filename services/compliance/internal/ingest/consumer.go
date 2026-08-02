package ingest

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

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
//
// MaxAge is a hard ceiling on how long ANY message (poisoned or not) can sit
// in this stream — WorkQueuePolicy only removes a message on Ack/Term, so
// without an age limit a class of permanently-failing message (there has
// already been one) grows the stream without bound forever.
func EnsureStream(ctx context.Context, js jetstream.JetStream, streamName string) (jetstream.Stream, error) {
	return js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{
		Name:      streamName,
		Subjects:  []string{"lokilinux.compliance.>"},
		Retention: jetstream.WorkQueuePolicy, // each message consumed exactly once by the ingest pool
		MaxAge:    24 * time.Hour,
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
		// Belt-and-suspenders alongside Term() below: if some future
		// error ever gets misclassified as transient, this still bounds
		// the damage instead of redelivering forever. BackOff spaces
		// retries out instead of NAK-ing straight back into a hot loop
		// with zero delay (what "MaxDeliver unset = -1, AckWait default,
		// no BackOff" actually did — confirmed live, ~35k log lines/min).
		MaxDeliver: 5,
		BackOff:    []time.Duration{1 * time.Second, 5 * time.Second, 30 * time.Second},
	})
	if err != nil {
		return fmt.Errorf("creating durable consumer %s: %w", durableName, err)
	}

	consumeCtx, err := consumer.Consume(func(msg jetstream.Msg) {
		if err := c.handle(ctx, msg); err != nil {
			c.log.Error("failed to ingest snapshot message", "subject", msg.Subject(), "error", err)
			if isPermanent(err) {
				// Never going to succeed on retry — Term so it's dropped
				// from this WorkQueue stream immediately instead of
				// redelivering (with BackOff still capped at MaxDeliver=5
				// as a fallback for anything that reaches here misclassified).
				_ = msg.Term()
			} else {
				// Transient (DB hiccup, etc.) — retry, but with a real
				// delay instead of an immediate NAK-triggered redelivery.
				_ = msg.NakWithDelay(5 * time.Second)
			}
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
		return Snapshot{}, newPermanentError("decoding snapshot message: %v", err)
	}

	agentID, err := uuid.Parse(payload.AgentID)
	if err != nil {
		return Snapshot{}, newPermanentError("snapshot message has invalid agent_id %q: %v", payload.AgentID, err)
	}

	return Snapshot{
		AgentID:     agentID,
		Domain:      payload.Domain,
		ContentHash: payload.ContentHash,
		Facts:       payload.Facts,
	}, nil
}
