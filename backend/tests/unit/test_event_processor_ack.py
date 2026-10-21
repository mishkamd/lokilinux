"""Guards for the event processor's delivery + ack discipline (MIS-139).

- the worker consumes from a durable JetStream consumer (not core NATS),
- a message is acked only AFTER its event is durably in ClickHouse,
- a failed flush leaves the message unacked (JetStream redelivers it),
- poison messages (malformed / invalid schema / duplicate) are acked so the
  consumer isn't stalled forever,
- if JetStream is unavailable the worker falls back to core NATS.
"""

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from lokilinux.workers.event_processor import EventProcessorWorker


class FakeMsg:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.acked = 0

    async def ack(self) -> None:
        self.acked += 1


class FakeSub:
    def __init__(self) -> None:
        self.unsubscribed = 0

    async def unsubscribe(self) -> None:
        self.unsubscribed += 1


class FakeJS:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sub_kwargs: dict[str, Any] = {}

    async def subscribe(self, subject: str, **kwargs: Any) -> FakeSub:
        if self.fail:
            raise RuntimeError("no jetstream")
        self.sub_kwargs = {"subject": subject, **kwargs}
        return FakeSub()


class FakeNats:
    def __init__(self, js: FakeJS | None = None) -> None:
        self._js = js
        self.core_subscriptions: list[str] = []
        self.published: list[tuple[str, bytes]] = []

    def jetstream(self) -> FakeJS:
        assert self._js is not None
        return self._js

    async def subscribe(self, subject: str, cb: Any = None) -> None:
        self.core_subscriptions.append(subject)

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))


class FakeCache:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def set_nx(self, key: str, ttl: int) -> bool:
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True


class FakeCH:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.inserted: list[list[Any]] = []

    async def insert(self, table: str, data: list[list[Any]], column_names: list[str]) -> None:
        if self.fail:
            raise RuntimeError("clickhouse down")
        self.inserted.extend(data)


def _event(**over: Any) -> bytes:
    payload = {
        "source": "agent",
        "type": "agent.heartbeat",
        "severity": "INFO",
        "host_id": "h1",
        "service": "svc",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(over)
    return json.dumps(payload).encode()


@pytest.mark.asyncio
async def test_worker_uses_durable_jetstream_consumer() -> None:
    js = FakeJS()
    nats = FakeNats(js)
    worker = EventProcessorWorker(nats, FakeCache(), FakeCH())
    await worker.start()

    assert nats.core_subscriptions == []  # NOT the core path
    assert js.sub_kwargs["durable"] == "event-processor"
    assert js.sub_kwargs["stream"] == "EVENTS"
    cfg = js.sub_kwargs["config"]
    assert cfg.ack_policy.name == "EXPLICIT"
    assert cfg.filter_subject == "lokilinux.events.raw.*"


@pytest.mark.asyncio
async def test_worker_falls_back_to_core_nats_when_jetstream_fails() -> None:
    nats = FakeNats(FakeJS(fail=True))
    worker = EventProcessorWorker(nats, FakeCache(), FakeCH())
    await worker.start()
    assert nats.core_subscriptions == ["lokilinux.events.raw.*"]


@pytest.mark.asyncio
async def test_message_is_acked_only_after_the_event_reaches_clickhouse() -> None:
    ch = FakeCH()
    worker = EventProcessorWorker(FakeNats(FakeJS()), FakeCache(), ch)
    msg = FakeMsg(_event())

    await worker._handle_raw(msg)
    # Buffered, not yet written -> not acked yet.
    assert not ch.inserted
    assert msg.acked == 0

    await worker._flush_once()
    assert ch.inserted, "the event should be written to ClickHouse"
    assert msg.acked == 1, "acked after the write"


@pytest.mark.asyncio
async def test_failed_flush_leaves_the_message_unacked() -> None:
    ch = FakeCH(fail=True)
    worker = EventProcessorWorker(FakeNats(FakeJS()), FakeCache(), ch)
    msg = FakeMsg(_event())

    await worker._handle_raw(msg)
    await worker._flush_once()

    assert msg.acked == 0, "a failed write must leave the message for redelivery"


@pytest.mark.asyncio
async def test_poison_messages_are_acked() -> None:
    worker = EventProcessorWorker(FakeNats(FakeJS()), FakeCache(), FakeCH())

    malformed = FakeMsg(b"not json")
    await worker._handle_raw(malformed)
    assert malformed.acked == 1

    invalid = FakeMsg(json.dumps({"source": "not-a-real-source"}).encode())
    await worker._handle_raw(invalid)
    assert invalid.acked == 1


@pytest.mark.asyncio
async def test_duplicate_event_is_acked_and_not_written_twice() -> None:
    ch = FakeCH()
    cache = FakeCache()
    worker = EventProcessorWorker(FakeNats(FakeJS()), cache, ch)
    payload = _event(event_id="11111111-1111-1111-1111-111111111111")

    first = FakeMsg(payload)
    second = FakeMsg(payload)
    await worker._handle_raw(first)
    await worker._handle_raw(second)
    await worker._flush_once()

    assert len(ch.inserted) == 1
    assert second.acked == 1
