import pytest

from lokilinux.signals.detectors import DetectedSignal
from lokilinux.signals.service import SignalService


class _FakeOccurrences:
    def __init__(self) -> None:
        self.added: list[dict] = []

    async def add(self, **kwargs) -> None:
        self.added.append(kwargs)


@pytest.mark.asyncio
async def test_upsert_creates_new_signal(db_session, fake_nats):
    occurrences = _FakeOccurrences()
    svc = SignalService(db_session, fake_nats, occurrences)

    detected = DetectedSignal(type="host.unreachable", severity="CRITICAL", host_id="host-1")
    row = await svc.upsert_signal(detected)

    assert row.type == "host.unreachable"
    assert row.severity == "CRITICAL"
    assert row.status == "OPEN"
    assert row.occurrence_count == 1
    assert len(occurrences.added) == 1
    assert len(fake_nats.published) == 1
    assert fake_nats.published[0][0] == "lokilinux.signals.detected"


@pytest.mark.asyncio
async def test_upsert_same_fingerprint_increments_occurrence_count(db_session, fake_nats):
    occurrences = _FakeOccurrences()
    svc = SignalService(db_session, fake_nats, occurrences)
    detected = DetectedSignal(type="job.failed", severity="HIGH", host_id="host-2")

    first = await svc.upsert_signal(detected)
    second = await svc.upsert_signal(detected)

    assert first.id == second.id
    assert second.occurrence_count == 2


@pytest.mark.asyncio
async def test_upsert_never_downgrades_severity(db_session, fake_nats):
    occurrences = _FakeOccurrences()
    svc = SignalService(db_session, fake_nats, occurrences)

    critical = DetectedSignal(type="compliance.violation", severity="CRITICAL", host_id="host-3", resource="r1")
    high = DetectedSignal(type="compliance.violation", severity="HIGH", host_id="host-3", resource="r1")

    await svc.upsert_signal(critical)
    row = await svc.upsert_signal(high)  # lower severity, same fingerprint

    assert row.severity == "CRITICAL"  # never downgraded
    assert row.occurrence_count == 2


@pytest.mark.asyncio
async def test_upsert_escalates_severity(db_session, fake_nats):
    occurrences = _FakeOccurrences()
    svc = SignalService(db_session, fake_nats, occurrences)

    medium = DetectedSignal(type="cpu.high", severity="MEDIUM", host_id="host-4")
    critical = DetectedSignal(type="cpu.high", severity="CRITICAL", host_id="host-4")

    await svc.upsert_signal(medium)
    row = await svc.upsert_signal(critical)

    assert row.severity == "CRITICAL"


@pytest.mark.asyncio
async def test_resolve_by_fingerprint_marks_resolved_and_publishes(db_session, fake_nats):
    occurrences = _FakeOccurrences()
    svc = SignalService(db_session, fake_nats, occurrences)
    await svc.upsert_signal(DetectedSignal(type="host.unreachable", severity="CRITICAL", host_id="host-5"))

    await svc.resolve_by_fingerprint("default", "host-5", "host.unreachable")

    published_subjects = [p[0] for p in fake_nats.published]
    assert "lokilinux.signals.resolved" in published_subjects


@pytest.mark.asyncio
async def test_resolve_by_fingerprint_is_noop_when_nothing_open(db_session, fake_nats):
    occurrences = _FakeOccurrences()
    svc = SignalService(db_session, fake_nats, occurrences)
    await svc.resolve_by_fingerprint("default", "host-does-not-exist", "host.unreachable")
    assert fake_nats.published == []
