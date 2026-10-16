"""MIS-9: a settings-DB outage must not switch the rate limit off.

The last good (enabled, limit) pair is kept in memory and reused while the
settings DB is unreachable, including after the 30s Redis config cache expires.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from lokilinux.middleware import rate_limit
from lokilinux.utils.local_counter import local_counter


@asynccontextmanager
async def _session_factory():
    yield None


@pytest.fixture
def settings(monkeypatch):
    """Fake settings table. Flip state["up"] to simulate the DB going down."""
    state = {"up": True, "enabled": True, "limit": 100}

    async def get_setting_value(_db, key):
        if not state["up"]:
            raise ConnectionError("settings db unreachable")
        return state["enabled"] if key == "security.rate_limit_enabled" else state["limit"]

    monkeypatch.setattr(rate_limit, "get_setting_value", get_setting_value)
    # Start from a clean process: no good read yet (schema defaults only).
    monkeypatch.setattr(rate_limit, "_last_good", (True, 120), raising=False)
    return state


@pytest.fixture
def app(fake_cache, monkeypatch):
    # Fixed clock: every request falls in one 60s window, so counts are deterministic.
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(time=lambda: 1_800_000_000.0))
    app = FastAPI()
    app.add_middleware(rate_limit.RateLimitMiddleware)
    app.state.cache = fake_cache
    app.state.session_factory = _session_factory

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_db_outage_reuses_last_good_config(fake_cache, settings):
    assert await rate_limit._rate_limit_config(fake_cache, _session_factory) == (True, 100)

    await fake_cache.invalidate(rate_limit._CONFIG_CACHE_KEY)  # Redis 30s TTL has expired
    settings["up"] = False

    assert await rate_limit._rate_limit_config(fake_cache, _session_factory) == (True, 100)


@pytest.mark.asyncio
async def test_db_outage_keeps_limit_of_100_enforced(app, fake_cache, settings):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/ping")).status_code == 200  # good read: limit 100

        await fake_cache.invalidate(rate_limit._CONFIG_CACHE_KEY)
        settings["up"] = False

        # 1 good-read request + 99 more = 100 allowed; the 101st must be rejected.
        for _ in range(99):
            assert (await client.get("/ping")).status_code == 200
        assert (await client.get("/ping")).status_code == 429


@pytest.mark.asyncio
async def test_db_down_before_any_good_read_uses_schema_defaults(fake_cache, settings):
    settings["up"] = False

    assert await rate_limit._rate_limit_config(fake_cache, _session_factory) == (True, 120)


@pytest.mark.asyncio
async def test_redis_outage_still_enforces_the_limit(app, fake_cache, settings, monkeypatch):
    """MIS-30 (3b): a Redis error on the request counter must not switch the limit off.
    Before the fix the middleware took incr()'s fail-open 0 and let every request through."""
    monkeypatch.setattr(local_counter, "_counts", {})

    async def redis_down(key, ttl):
        return None

    async def incr_fail_open(key, ttl):  # cache.incr keeps its fail-open 0 for other callers
        return 0

    monkeypatch.setattr(fake_cache, "incr_checked", redis_down, raising=False)
    monkeypatch.setattr(fake_cache, "incr", incr_fail_open)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(100):
            assert (await client.get("/ping")).status_code == 200
        assert (await client.get("/ping")).status_code == 429
