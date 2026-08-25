import pytest
from sqlalchemy import select

from lokilinux.correlation.rules import RuleCache, ensure_default_rules
from lokilinux.signals.models import CorrelationRule


@pytest.mark.asyncio
async def test_ensure_default_rules_creates_the_seed_rule(db_session):
    await ensure_default_rules(db_session)
    row = (
        await db_session.execute(
            select(CorrelationRule).where(CorrelationRule.name == "application_degradation")
        )
    ).scalar_one()
    assert row.threshold_score == 60
    assert row.window_seconds == 300
    assert {c["signal"] for c in row.conditions} == {
        "cpu.high", "load.high", "http.latency.high", "http.error_rate.high",
    }


@pytest.mark.asyncio
async def test_ensure_default_rules_is_idempotent(db_session):
    await ensure_default_rules(db_session)
    await ensure_default_rules(db_session)  # must not raise a unique-constraint error
    rows = (
        await db_session.execute(
            select(CorrelationRule).where(CorrelationRule.name == "application_degradation")
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_rule_cache_loads_enabled_rules(db_session):
    await ensure_default_rules(db_session)
    cache = RuleCache()
    rules = await cache.get_enabled_rules(db_session)
    assert any(r.name == "application_degradation" for r in rules)


@pytest.mark.asyncio
async def test_rule_cache_serves_from_cache_within_ttl(db_session, monkeypatch):
    await ensure_default_rules(db_session)
    cache = RuleCache()
    first = await cache.get_enabled_rules(db_session)

    calls = {"n": 0}
    real_execute = db_session.execute

    async def _counting_execute(*args, **kwargs):
        calls["n"] += 1
        return await real_execute(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", _counting_execute)
    second = await cache.get_enabled_rules(db_session)

    assert calls["n"] == 0  # served from cache, no DB round-trip
    assert first == second
