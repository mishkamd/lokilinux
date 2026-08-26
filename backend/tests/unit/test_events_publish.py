import json

import pytest

from lokilinux.events.publish import emit, is_pipeline_enabled
from lokilinux.nats_topics import EVENT_RAW


class _FakeNats:
    def __init__(self, *, fail: bool = False) -> None:
        self.published: list[tuple[str, bytes]] = []
        self._fail = fail

    async def publish(self, subject: str, payload: bytes) -> None:
        if self._fail:
            raise RuntimeError("nats unreachable")
        self.published.append((subject, payload))


class _FakeCache:
    def __init__(self, *, cached_value=None) -> None:
        self._store: dict = {}
        if cached_value is not None:
            self._store["settings:observability:event_pipeline_enabled"] = cached_value

    async def get_cached(self, key: str):
        return self._store.get(key)

    async def set_cached(self, key: str, value, ttl=None) -> None:
        self._store[key] = value


@pytest.mark.asyncio
async def test_emit_publishes_to_source_scoped_subject():
    nats = _FakeNats()
    await emit(nats, "agent", "host.heartbeat.ok", host_id="host-1")
    assert len(nats.published) == 1
    subject, payload = nats.published[0]
    assert subject == f"{EVENT_RAW}.agent"
    body = json.loads(payload)
    assert body["source"] == "agent"
    assert body["type"] == "host.heartbeat.ok"
    assert body["host_id"] == "host-1"
    assert body["tenant_id"] == "default"
    assert "event_id" in body and "timestamp" in body


@pytest.mark.asyncio
async def test_emit_swallows_nats_failure():
    nats = _FakeNats(fail=True)
    await emit(nats, "agent", "host.heartbeat.ok")  # must not raise


@pytest.mark.asyncio
async def test_is_pipeline_enabled_reads_from_cache_when_present():
    cache = _FakeCache(cached_value=False)
    assert await is_pipeline_enabled(cache, db=None) is False


@pytest.mark.asyncio
async def test_is_pipeline_enabled_fails_open_when_settings_lookup_errors():
    cache = _FakeCache()

    class _BoomDB:
        async def execute(self, *_a, **_kw):
            raise RuntimeError("db unreachable")

    assert await is_pipeline_enabled(cache, db=_BoomDB()) is True
