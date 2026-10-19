"""A cache hit must refresh the process's last-good value (MIS-9, MIS-58).

Without that, a process that only ever sees cache hits keeps a stale last-good value:
another worker may have changed the setting since, and an outage would then restore
the old one.
"""

from contextlib import asynccontextmanager

import pytest

from lokilinux.events import publish
from lokilinux.middleware import rate_limit
from lokilinux.settings_schema import SETTINGS_SCHEMA

_PIPELINE_DEFAULT = SETTINGS_SCHEMA["observability"]["event_pipeline_enabled"][1]


@asynccontextmanager
async def _session_factory():
    yield None


@pytest.fixture
def db_down(monkeypatch):
    """Settings lookups fail; each module starts from its schema default."""

    async def get_setting_value(_db, key):
        raise ConnectionError("settings db unreachable")

    monkeypatch.setattr(publish, "get_setting_value", get_setting_value)
    monkeypatch.setattr(rate_limit, "get_setting_value", get_setting_value)
    monkeypatch.setattr(publish, "_last_good", _PIPELINE_DEFAULT, raising=False)
    monkeypatch.setattr(rate_limit, "_last_good", (True, 120), raising=False)


@pytest.mark.asyncio
async def test_pipeline_cache_hit_refreshes_last_good(fake_cache, db_down):
    await fake_cache.set_cached(publish._PIPELINE_ENABLED_CACHE_KEY, False, ttl=30)
    assert await publish.is_pipeline_enabled(fake_cache, None) is False  # cache hit

    await fake_cache.invalidate(publish._PIPELINE_ENABLED_CACHE_KEY)  # 30s TTL expired
    assert await publish.is_pipeline_enabled(fake_cache, None) is False


@pytest.mark.asyncio
async def test_rate_limit_cache_hit_refreshes_last_good(fake_cache, db_down):
    await fake_cache.set_cached(
        rate_limit._CONFIG_CACHE_KEY, {"enabled": True, "limit": 5}, ttl=30
    )
    assert await rate_limit._rate_limit_config(fake_cache, _session_factory) == (True, 5)

    await fake_cache.invalidate(rate_limit._CONFIG_CACHE_KEY)  # 30s TTL expired
    assert await rate_limit._rate_limit_config(fake_cache, _session_factory) == (True, 5)
