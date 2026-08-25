from types import SimpleNamespace
from uuid import uuid4

import pytest

from lokilinux.correlation.evaluator import CorrelationEvaluator


class _FakeZSetCache:
    """In-memory ZADD/ZRANGEBYSCORE/EXPIRE/SETNX — enough for the evaluator,
    no real TTL semantics (tests don't need time to actually pass)."""

    def __init__(self) -> None:
        self._zsets: dict[str, dict[str, float]] = {}
        self._locks: set[str] = set()

    async def zadd(self, key: str, member: str, score: float) -> None:
        self._zsets.setdefault(key, {})[member] = score

    async def zrangebyscore(self, key: str, min_score: float, max_score: float) -> list[str]:
        return [m for m, s in self._zsets.get(key, {}).items() if min_score <= s <= max_score]

    async def expire(self, key: str, ttl: int) -> None:
        pass

    async def set_nx(self, key: str, ttl: int) -> bool:
        if key in self._locks:
            return False
        self._locks.add(key)
        return True


def _rule(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        window_seconds=300,
        group_by=["host_id"],
        conditions=[
            {"signal": "cpu.high", "weight": 20},
            {"signal": "load.high", "weight": 20},
            {"signal": "http.latency.high", "weight": 25},
            {"signal": "http.error_rate.high", "weight": 35},
        ],
        threshold_score=60,
        incident_type="application_degradation",
        suppressions=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _signal(**overrides) -> SimpleNamespace:
    base = {"type": "cpu.high", "host_id": "host-1"}
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_below_threshold_produces_no_candidate():
    evaluator = CorrelationEvaluator(_FakeZSetCache())
    rule = _rule()
    candidates = await evaluator.on_signal([rule], _signal(type="cpu.high"))
    assert candidates == []  # 20 < 60


@pytest.mark.asyncio
async def test_reaching_threshold_across_distinct_signals_fires():
    cache = _FakeZSetCache()
    evaluator = CorrelationEvaluator(cache)
    rule = _rule()

    await evaluator.on_signal([rule], _signal(type="cpu.high"))          # 20
    await evaluator.on_signal([rule], _signal(type="load.high"))         # +20 = 40
    candidates = await evaluator.on_signal([rule], _signal(type="http.latency.high"))  # +25 = 65

    assert len(candidates) == 1
    assert candidates[0].score == 65
    assert set(candidates[0].member_types) == {"cpu.high", "load.high", "http.latency.high"}


@pytest.mark.asyncio
async def test_repeat_same_signal_does_not_inflate_score():
    cache = _FakeZSetCache()
    evaluator = CorrelationEvaluator(cache)
    rule = _rule()

    candidates = []
    for _ in range(5):
        candidates = await evaluator.on_signal([rule], _signal(type="cpu.high"))
    assert candidates == []  # still just 20, never crosses 60 no matter how many repeats


@pytest.mark.asyncio
async def test_signal_type_not_in_rule_conditions_is_ignored():
    evaluator = CorrelationEvaluator(_FakeZSetCache())
    rule = _rule()
    candidates = await evaluator.on_signal([rule], _signal(type="disk.usage.high"))
    assert candidates == []


@pytest.mark.asyncio
async def test_double_fire_guarded_by_lock():
    cache = _FakeZSetCache()
    evaluator = CorrelationEvaluator(cache)
    rule = _rule(threshold_score=20)  # single signal already crosses it

    first = await evaluator.on_signal([rule], _signal(type="cpu.high"))
    second = await evaluator.on_signal([rule], _signal(type="cpu.high"))

    assert len(first) == 1
    assert second == []  # lock still held — redelivery doesn't double-fire


@pytest.mark.asyncio
async def test_root_signal_is_highest_weight_member():
    cache = _FakeZSetCache()
    evaluator = CorrelationEvaluator(cache)
    rule = _rule()

    await evaluator.on_signal([rule], _signal(type="cpu.high"))
    await evaluator.on_signal([rule], _signal(type="load.high"))
    candidates = await evaluator.on_signal([rule], _signal(type="http.error_rate.high"))  # weight 35, highest

    assert candidates[0].root_signal_type == "http.error_rate.high"


@pytest.mark.asyncio
async def test_tenant_isolation_same_host_different_tenants_do_not_share_window():
    cache = _FakeZSetCache()
    evaluator = CorrelationEvaluator(cache)
    rule = _rule(threshold_score=40)

    await evaluator.on_signal([rule], _signal(type="cpu.high"), tenant_id="tenant-a")
    candidates_a = await evaluator.on_signal([rule], _signal(type="load.high"), tenant_id="tenant-a")
    candidates_b = await evaluator.on_signal([rule], _signal(type="load.high"), tenant_id="tenant-b")

    assert len(candidates_a) == 1  # tenant-a: cpu.high + load.high = 40, fires
    assert candidates_b == []      # tenant-b: only load.high = 20, its own window, doesn't inherit tenant-a's cpu.high


@pytest.mark.asyncio
async def test_different_hosts_do_not_share_a_window():
    cache = _FakeZSetCache()
    evaluator = CorrelationEvaluator(cache)
    rule = _rule(threshold_score=40)

    await evaluator.on_signal([rule], _signal(type="cpu.high", host_id="host-a"))
    candidates_a = await evaluator.on_signal([rule], _signal(type="load.high", host_id="host-a"))
    candidates_b = await evaluator.on_signal([rule], _signal(type="load.high", host_id="host-b"))

    assert len(candidates_a) == 1
    assert candidates_b == []


@pytest.mark.asyncio
async def test_suppressed_rule_produces_no_candidate():
    from datetime import datetime, timezone

    cache = _FakeZSetCache()
    evaluator = CorrelationEvaluator(cache)
    now = datetime.now(timezone.utc)
    day = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[now.weekday()]
    rule = _rule(threshold_score=20, suppressions=[{"from": f"{day} 00:00", "to": f"{day} 23:59"}])

    candidates = await evaluator.on_signal([rule], _signal(type="cpu.high"))
    assert candidates == []
