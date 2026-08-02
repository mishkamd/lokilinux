package scheduler

import (
	"context"
	"errors"

	"github.com/nats-io/nats.go/jetstream"
)

// natsKV adapts a real jetstream.KeyValue to this package's KVStore
// interface. Needed because Go interface satisfaction requires identical
// method signatures — jetstream.KeyValue.Get returns
// (jetstream.KeyValueEntry, error), not (scheduler.KVEntry, error), even
// though KeyValueEntry's method set already satisfies KVEntry — so a
// production caller can't pass a jetstream.KeyValue directly where KVStore
// is expected without this thin wrapper.
type natsKV struct {
	kv jetstream.KeyValue
}

// NewNATSKVStore wraps a real jetstream.KeyValue bucket for use by
// LeaderElector. The bucket must already be created with a TTL
// (jetstream.KeyValueConfig{TTL: ...}) — see docs/compliance/02-GO-SERVICE.md §4.
func NewNATSKVStore(kv jetstream.KeyValue) KVStore {
	return &natsKV{kv: kv}
}

func (n *natsKV) Get(ctx context.Context, key string) (KVEntry, error) {
	entry, err := n.kv.Get(ctx, key)
	if err != nil {
		if errors.Is(err, jetstream.ErrKeyNotFound) {
			return nil, ErrKeyNotFound
		}
		return nil, err
	}
	return entry, nil
}

func (n *natsKV) Create(ctx context.Context, key string, value []byte) (uint64, error) {
	return n.kv.Create(ctx, key, value)
}

func (n *natsKV) Update(ctx context.Context, key string, value []byte, revision uint64) (uint64, error) {
	return n.kv.Update(ctx, key, value, revision)
}
