"""MIS-30 (3b): with Redis down, the events and OTLP routers must still enforce the
per-principal event rate limit.

cache.incr() fails open (returns 0) on a Redis error, so these routers used to count
nothing during an outage. They now call incr_checked and count in this process when it
returns None, the same way the request limiter does.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

import lokilinux.api.v1.routers.events as events_mod
import lokilinux.api.v1.routers.otlp as otlp_mod

_LIMIT = 2
_EVENT = {"source": "agent", "type": "host.heartbeat.ok"}
_HEADERS = {"content-type": "application/x-protobuf"}


@pytest.fixture
def redis_down(fake_cache, monkeypatch):
    """Redis errors: incr_checked returns None and incr keeps its fail-open 0."""

    async def incr_checked(key, ttl):
        return None

    async def incr_fail_open(key, ttl):
        return 0

    monkeypatch.setattr(fake_cache, "incr_checked", incr_checked)
    monkeypatch.setattr(fake_cache, "incr", incr_fail_open)


@pytest.fixture
def small_limit(monkeypatch):
    settings = SimpleNamespace(event_rate_per_agent_per_min=_LIMIT)
    monkeypatch.setattr(events_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(otlp_mod, "get_settings", lambda: settings)


@pytest.mark.asyncio
async def test_events_post_returns_429_over_limit_while_redis_down(client, redis_down, small_limit):
    for _ in range(_LIMIT):
        assert (await client.post("/api/v1/events", json=_EVENT)).status_code == 200
    assert (await client.post("/api/v1/events", json=_EVENT)).status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/otlp/v1/logs", "/api/v1/otlp/v1/traces"])
async def test_otlp_post_returns_429_over_limit_while_redis_down(client, redis_down, small_limit, path):
    # An empty export request is valid OTLP and reaches the limiter without publishing anything.
    for _ in range(_LIMIT):
        assert (await client.post(path, content=b"", headers=_HEADERS)).status_code == 200
    assert (await client.post(path, content=b"", headers=_HEADERS)).status_code == 429


@pytest.mark.asyncio
async def test_events_and_otlp_share_one_bucket_per_principal(
    client, redis_down, small_limit, current_user
):
    # Same logical key as Redis (rate:ev:{principal}), so both endpoints draw from one bucket.
    for _ in range(_LIMIT):
        assert (await client.post("/api/v1/events", json=_EVENT)).status_code == 200
    assert (await client.post("/api/v1/otlp/v1/logs", content=b"", headers=_HEADERS)).status_code == 429

    # Another principal has its own bucket. The client's auth override returns this same dict.
    current_user["id"] = str(uuid4())
    assert (await client.post("/api/v1/events", json=_EVENT)).status_code == 200
