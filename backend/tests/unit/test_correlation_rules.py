from types import SimpleNamespace

import pytest
from sqlalchemy import select

from lokilinux.correlation.rules import DEFAULT_RULES, RuleCache, ensure_default_rules
from lokilinux.signals.detectors import DETECTORS, _METRIC_RULES
from lokilinux.signals.models import CorrelationRule


def test_default_rules_are_reachable():
    """Every shipped rule must be satisfiable by signals the detector
    registry can actually emit — otherwise threshold_score can never be
    crossed and the rule silently never fires in production (see
    docs/superpowers/plans/2026-08-25-*: application_degradation shipped
    referencing load.high/http.*.high, which nothing produces)."""
    # payload.severity=HIGH so conditional detectors (e.g. compliance drift,
    # which only fires on HIGH/CRITICAL) also report their producible type.
    fake_event = SimpleNamespace(host_id="h", payload={"severity": "HIGH"})
    producible_types = set()
    for fn in DETECTORS.values():
        signal = fn(fake_event)
        assert signal is not None
        producible_types.add(signal.type)
    producible_types |= {sig_type for _, sig_type, _, _ in _METRIC_RULES}

    for rule in DEFAULT_RULES:
        weights = {c["signal"]: c["weight"] for c in rule["conditions"]}
        reachable_score = sum(w for sig, w in weights.items() if sig in producible_types)
        assert reachable_score >= rule["threshold_score"], (
            f"rule {rule['name']!r} needs score {rule['threshold_score']} but only "
            f"{reachable_score} is reachable from producible signals {producible_types}"
        )


@pytest.mark.asyncio
async def test_ensure_default_rules_creates_the_seed_rules(db_session):
    await ensure_default_rules(db_session)
    for spec in DEFAULT_RULES:
        row = (
            await db_session.execute(
                select(CorrelationRule).where(CorrelationRule.name == spec["name"])
            )
        ).scalar_one()
        assert row.threshold_score == spec["threshold_score"]
        assert row.window_seconds == spec["window_seconds"]
        assert {c["signal"] for c in row.conditions} == {c["signal"] for c in spec["conditions"]}


@pytest.mark.asyncio
async def test_ensure_default_rules_is_idempotent(db_session):
    await ensure_default_rules(db_session)
    await ensure_default_rules(db_session)  # must not raise a unique-constraint error
    rows = (
        await db_session.execute(
            select(CorrelationRule).where(CorrelationRule.name == DEFAULT_RULES[0]["name"])
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_rule_cache_loads_enabled_rules(db_session):
    await ensure_default_rules(db_session)
    cache = RuleCache()
    rules = await cache.get_enabled_rules(db_session)
    seeded_names = {spec["name"] for spec in DEFAULT_RULES}
    assert seeded_names <= {r.name for r in rules}


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
