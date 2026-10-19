"""MIS-58: a settings-DB outage must not re-enable the event pipeline kill switch.

is_pipeline_enabled() keeps the last good value of observability.event_pipeline_enabled
in memory and returns it while the settings DB is unreachable, including after the
30s Redis cache expires. Before any good read, it returns the schema default.
"""

import pytest

from lokilinux.events import publish
from lokilinux.settings_schema import SETTINGS_SCHEMA

_DEFAULT = SETTINGS_SCHEMA["observability"]["event_pipeline_enabled"][1]


@pytest.fixture
def settings(monkeypatch):
    """Fake settings table. Flip state["up"] to simulate the DB going down."""
    state = {"up": True, "enabled": _DEFAULT}

    async def get_setting_value(_db, key):
        if not state["up"]:
            raise ConnectionError("settings db unreachable")
        return state["enabled"]

    monkeypatch.setattr(publish, "get_setting_value", get_setting_value)
    # Start from a clean process: no good read yet (schema default only).
    monkeypatch.setattr(publish, "_last_good", _DEFAULT, raising=False)
    return state


@pytest.mark.asyncio
async def test_outage_after_good_false_read_keeps_false(fake_cache, settings):
    settings["enabled"] = False
    assert await publish.is_pipeline_enabled(fake_cache, None) is False  # good read

    await fake_cache.invalidate(publish._PIPELINE_ENABLED_CACHE_KEY)  # Redis 30s TTL has expired
    settings["up"] = False

    assert await publish.is_pipeline_enabled(fake_cache, None) is False


@pytest.mark.asyncio
async def test_outage_before_any_good_read_uses_schema_default(fake_cache, settings):
    settings["up"] = False

    assert await publish.is_pipeline_enabled(fake_cache, None) is _DEFAULT


@pytest.mark.asyncio
async def test_outage_uses_most_recent_good_read(fake_cache, settings):
    assert await publish.is_pipeline_enabled(fake_cache, None) is True  # good read

    await fake_cache.invalidate(publish._PIPELINE_ENABLED_CACHE_KEY)
    settings["enabled"] = False
    assert await publish.is_pipeline_enabled(fake_cache, None) is False  # kill switch flipped

    await fake_cache.invalidate(publish._PIPELINE_ENABLED_CACHE_KEY)
    settings["up"] = False

    assert await publish.is_pipeline_enabled(fake_cache, None) is False
