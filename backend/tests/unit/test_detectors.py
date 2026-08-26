from types import SimpleNamespace

import pytest

from lokilinux.signals.detectors import (
    detect_host_unreachable,
    detect_job_failed,
    detect_metric_samples,
)


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict = {}

    async def incr(self, key: str, ttl: int) -> int:
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    async def invalidate(self, key: str) -> None:
        self._store.pop(key, None)


def _event(**overrides):
    base = {"host_id": "host-1", "payload": {}}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_host_unreachable_is_critical():
    sig = detect_host_unreachable(_event())
    assert sig.type == "host.unreachable"
    assert sig.severity == "CRITICAL"
    assert sig.host_id == "host-1"


def test_job_failed_is_high():
    sig = detect_job_failed(_event(payload={"job_id": "job-42"}))
    assert sig.type == "job.failed"
    assert sig.severity == "HIGH"
    assert sig.metadata["job_id"] == "job-42"


@pytest.mark.asyncio
async def test_disk_fires_on_single_sample():
    cache = _FakeCache()
    signals = await detect_metric_samples(_event(payload={"disk": 95}), cache)
    assert len(signals) == 1
    assert signals[0].type == "disk.usage.high"


@pytest.mark.asyncio
async def test_cpu_requires_two_consecutive_samples():
    cache = _FakeCache()
    first = await detect_metric_samples(_event(payload={"cpu": 95}), cache)
    assert first == []  # only 1 sample so far
    second = await detect_metric_samples(_event(payload={"cpu": 95}), cache)
    assert len(second) == 1
    assert second[0].type == "cpu.high"


@pytest.mark.asyncio
async def test_cpu_sustain_counter_resets_below_threshold():
    cache = _FakeCache()
    await detect_metric_samples(_event(payload={"cpu": 95}), cache)  # 1st over-threshold
    await detect_metric_samples(_event(payload={"cpu": 10}), cache)  # resets
    signals = await detect_metric_samples(_event(payload={"cpu": 95}), cache)  # back to 1st again
    assert signals == []


@pytest.mark.asyncio
async def test_metric_sample_with_no_recognized_keys_detects_nothing():
    cache = _FakeCache()
    signals = await detect_metric_samples(_event(payload={"unrelated": 1}), cache)
    assert signals == []
