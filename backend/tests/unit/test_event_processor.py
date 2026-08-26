import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lokilinux.workers.event_processor import EventProcessorWorker


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict = {}

    async def get_cached(self, key: str):
        return self._store.get(key)

    async def set_cached(self, key: str, value, ttl=None) -> None:
        self._store[key] = value


class _FakeCH:
    def __init__(self) -> None:
        self.inserted = []

    async def insert(self, table, data, column_names) -> None:
        self.inserted.append((table, data, column_names))


class _FakeNats:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))


def _msg(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps(payload).encode())


def _raw_event(**overrides) -> dict:
    base = {
        "event_id": str(uuid4()),
        "tenant_id": "default",
        "source": "agent",
        "type": "host.heartbeat.ok",
        "severity": "INFO",
        "host_id": "host-1",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_valid_event_is_persisted_and_republished_normalized():
    cache, ch, nats = _FakeCache(), _FakeCH(), _FakeNats()
    worker = EventProcessorWorker(nats, cache, ch)
    await worker._handle_raw(_msg(_raw_event()))
    await worker.repository.flush()

    assert len(ch.inserted) == 1
    assert len(nats.published) == 1
    subject, payload = nats.published[0]
    assert subject == "lokilinux.events.normalized"
    body = json.loads(payload)
    assert body["source"] == "agent"
    assert "fingerprint" in body


@pytest.mark.asyncio
async def test_duplicate_event_id_is_deduped():
    cache, ch, nats = _FakeCache(), _FakeCH(), _FakeNats()
    worker = EventProcessorWorker(nats, cache, ch)
    raw = _raw_event()
    await worker._handle_raw(_msg(raw))
    await worker._handle_raw(_msg(raw))  # redelivery, same event_id
    await worker.repository.flush()

    assert len(nats.published) == 1
    assert len(ch.inserted) == 1


@pytest.mark.asyncio
async def test_malformed_json_does_not_raise():
    cache, ch, nats = _FakeCache(), _FakeCH(), _FakeNats()
    worker = EventProcessorWorker(nats, cache, ch)
    await worker._handle_raw(SimpleNamespace(data=b"{not-json"))  # must not raise
    assert nats.published == []


@pytest.mark.asyncio
async def test_invalid_schema_is_dropped_not_raised():
    cache, ch, nats = _FakeCache(), _FakeCH(), _FakeNats()
    worker = EventProcessorWorker(nats, cache, ch)
    await worker._handle_raw(_msg(_raw_event(source="not-a-real-source")))
    assert nats.published == []


@pytest.mark.asyncio
async def test_server_stamps_timestamp_when_producer_omits_it():
    cache, ch, nats = _FakeCache(), _FakeCH(), _FakeNats()
    worker = EventProcessorWorker(nats, cache, ch)
    await worker._handle_raw(_msg(_raw_event()))
    subject, payload = nats.published[0]
    body = json.loads(payload)
    ts = datetime.fromisoformat(body["timestamp"])
    assert abs((datetime.now(timezone.utc) - ts).total_seconds()) < 5
