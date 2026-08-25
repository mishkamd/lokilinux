from datetime import datetime, timezone
from uuid import uuid4

import pytest

from lokilinux.events import repository as repo_module
from lokilinux.events.repository import EventRepository
from lokilinux.events.schemas import NormalizedEvent


def _mk_event(**overrides) -> NormalizedEvent:
    base = dict(
        source="agent",
        type="host.heartbeat.ok",
        severity="INFO",
        host_id="host-1",
        service=None,
        payload={},
        event_id=uuid4(),
        tenant_id="default",
        timestamp=datetime.now(timezone.utc),
        fingerprint="a" * 32,
    )
    base.update(overrides)
    return NormalizedEvent(**base)


class FakeCH:
    def __init__(self, fail_times: int = 0) -> None:
        self.inserted: list[tuple[str, list, list]] = []
        self._fail_times = fail_times

    async def insert(self, table, data, column_names) -> None:
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("clickhouse unreachable")
        self.inserted.append((table, data, column_names))


@pytest.fixture(autouse=True)
def _small_batch(monkeypatch):
    """Shrink the module constants so tests don't need 1000+ events."""
    monkeypatch.setattr(repo_module, "EVENT_INSERT_BATCH", 3)
    monkeypatch.setattr(repo_module, "EVENT_INSERT_FLUSH_SEC", 999.0)
    monkeypatch.setattr(repo_module, "EVENT_BUFFER_MAX", 5)


@pytest.mark.asyncio
async def test_add_below_threshold_does_not_flush():
    ch = FakeCH()
    repo = EventRepository(ch)
    await repo.add(_mk_event())
    await repo.add(_mk_event())
    assert ch.inserted == []


@pytest.mark.asyncio
async def test_add_reaching_batch_size_flushes_automatically():
    ch = FakeCH()
    repo = EventRepository(ch)
    for _ in range(3):
        await repo.add(_mk_event())
    assert len(ch.inserted) == 1
    table, data, columns = ch.inserted[0]
    assert table == "events"
    assert len(data) == 3
    assert "fingerprint" in columns


@pytest.mark.asyncio
async def test_explicit_flush_drains_partial_buffer():
    ch = FakeCH()
    repo = EventRepository(ch)
    await repo.add(_mk_event())
    await repo.flush()
    assert len(ch.inserted) == 1
    assert len(ch.inserted[0][1]) == 1


@pytest.mark.asyncio
async def test_flush_on_empty_buffer_is_noop():
    ch = FakeCH()
    repo = EventRepository(ch)
    await repo.flush()
    assert ch.inserted == []


@pytest.mark.asyncio
async def test_failed_flush_requeues_for_next_attempt():
    ch = FakeCH(fail_times=1)
    repo = EventRepository(ch)
    await repo.add(_mk_event())
    await repo.flush()  # fails, requeues
    assert ch.inserted == []
    assert len(repo._buffer) == 1
    await repo.flush()  # succeeds this time
    assert len(ch.inserted) == 1


@pytest.mark.asyncio
async def test_backpressure_never_drops_error_or_critical():
    ch = FakeCH(fail_times=999)  # every flush fails -> forces overflow handling
    repo = EventRepository(ch)
    severities = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "DEBUG"]
    for sev in severities:
        await repo.add(_mk_event(severity=sev))
        await repo.flush()  # each add() at batch=3 may or may not trigger; force it anyway

    remaining = [row[5] for row in repo._buffer]
    assert "ERROR" in remaining
    assert "CRITICAL" in remaining
    assert len(repo._buffer) <= repo_module.EVENT_BUFFER_MAX


def _raw_row(severity: str) -> list:
    return [None, "id", "default", "agent", "type", severity, "h", "s", "fp", 1, "{}"]


@pytest.mark.asyncio
async def test_backpressure_drops_debug_before_an_older_warning():
    """Severity priority beats age: a newer DEBUG row is dropped while an
    older WARNING row (earlier in the buffer) survives."""
    ch = FakeCH()
    repo = EventRepository(ch)
    repo._buffer = [_raw_row(s) for s in ["WARNING", "DEBUG", "WARNING", "DEBUG", "DEBUG", "DEBUG"]]

    await repo._requeue_with_backpressure([])

    remaining = [row[5] for row in repo._buffer]
    assert len(remaining) == repo_module.EVENT_BUFFER_MAX
    assert remaining.count("WARNING") == 2  # both WARNING rows survive
    assert remaining.count("DEBUG") == 3    # the oldest DEBUG was dropped
