from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from lokilinux.events.fingerprint import fingerprint
from lokilinux.incidents.models import Incident, IncidentSignal, IncidentTimeline
from lokilinux.incidents.service import IncidentService
from lokilinux.models.alert import Alert
from lokilinux.signals.models import CorrelationRule, Signal


class _FakeCache:
    def __init__(self) -> None:
        self._locks: set = set()

    async def set_nx(self, key: str, ttl: int) -> bool:
        if key in self._locks:
            return False
        self._locks.add(key)
        return True


class _FakeCH:
    def __init__(self) -> None:
        self.inserted: list = []

    async def insert(self, table, data, column_names) -> None:
        self.inserted.append((table, data, column_names))


async def _make_signal(db_session, *, host_id: str, sig_type: str, status: str = "OPEN", last_seen=None) -> Signal:
    now = datetime.now(timezone.utc)
    sig = Signal(
        tenant_id="default", type=sig_type, severity="HIGH", status=status,
        fingerprint=fingerprint("default", host_id, sig_type, None),
        first_seen=now, last_seen=last_seen or now,
    )
    db_session.add(sig)
    await db_session.flush()
    return sig


async def _make_rule(db_session, **overrides) -> CorrelationRule:
    """A real CorrelationRule row — Incident.correlation_rule_id is a real FK,
    a fabricated SimpleNamespace id would violate the constraint."""
    base = dict(
        tenant_id="default", name=f"test-rule-{uuid4()}", enabled=True, window_seconds=300,
        group_by=["host_id"], conditions=[{"signal": "cpu.high", "weight": 60}],
        threshold_score=60, incident_type="application_degradation", incident_severity="CRITICAL",
    )
    base.update(overrides)
    rule = CorrelationRule(**base)
    db_session.add(rule)
    await db_session.flush()
    return rule


def _candidate(rule, *, host_id: str, member_types: list, score: int, root_signal_type: str, group_key=None):
    return SimpleNamespace(
        rule=rule, group_key=group_key or str(uuid4()), group_values={"host_id": host_id},
        member_types=member_types, score=score, root_signal_type=root_signal_type,
    )


@pytest.mark.asyncio
async def test_open_from_candidate_creates_incident_links_signals_and_timeline(db_session, fake_nats):
    host_id = "host-1"
    sig1 = await _make_signal(db_session, host_id=host_id, sig_type="cpu.high")
    sig2 = await _make_signal(db_session, host_id=host_id, sig_type="load.high")
    rule = await _make_rule(db_session)
    candidate = _candidate(rule, host_id=host_id, member_types=["cpu.high", "load.high"], score=65, root_signal_type="load.high")

    svc = IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH())
    incident = await svc.open_from_candidate(candidate)

    assert incident.type == "application_degradation"
    assert incident.status == "OPEN"
    assert incident.root_cause_signal_id == sig2.id  # root_signal_type == load.high

    links = (await db_session.execute(select(IncidentSignal).where(IncidentSignal.incident_id == incident.id))).scalars().all()
    assert {link.signal_id for link in links} == {sig1.id, sig2.id}

    timeline = (await db_session.execute(select(IncidentTimeline).where(IncidentTimeline.incident_id == incident.id))).scalars().all()
    kinds = [t.kind for t in timeline]
    assert kinds.count("created") == 1
    assert kinds.count("signal") == 2

    alerts = (await db_session.execute(select(Alert).where(Alert.incident_id == incident.id))).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].title.startswith("Incident:")


@pytest.mark.asyncio
async def test_second_candidate_same_group_key_attaches_instead_of_duplicating(db_session, fake_nats):
    host_id = "host-2"
    group_key = "fixed-group-key"
    sig1 = await _make_signal(db_session, host_id=host_id, sig_type="cpu.high")
    rule = await _make_rule(db_session)
    svc = IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH())

    first = await svc.open_from_candidate(
        _candidate(rule, host_id=host_id, member_types=["cpu.high"], score=20, root_signal_type="cpu.high", group_key=group_key)
    )

    sig2 = await _make_signal(db_session, host_id=host_id, sig_type="http.error_rate.high")
    second = await svc.open_from_candidate(
        _candidate(rule, host_id=host_id, member_types=["cpu.high", "http.error_rate.high"], score=55,
                   root_signal_type="http.error_rate.high", group_key=group_key)
    )

    assert first.id == second.id  # same incident, not a new one

    rows = (await db_session.execute(select(Incident).where(Incident.group_key == group_key))).scalars().all()
    assert len(rows) == 1

    links = (await db_session.execute(select(IncidentSignal).where(IncidentSignal.incident_id == first.id))).scalars().all()
    assert {link.signal_id for link in links} == {sig1.id, sig2.id}

    alerts = (await db_session.execute(select(Alert).where(Alert.incident_id == first.id))).scalars().all()
    assert len(alerts) == 1  # alert created exactly once, not again on re-attach


@pytest.mark.asyncio
async def test_ack_resolve_reopen_flow(db_session, fake_nats):
    host_id = "host-3"
    sig = await _make_signal(db_session, host_id=host_id, sig_type="cpu.high")
    rule = await _make_rule(db_session)
    svc = IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH())
    incident = await svc.open_from_candidate(
        _candidate(rule, host_id=host_id, member_types=["cpu.high"], score=60, root_signal_type="cpu.high")
    )

    acked = await svc.ack(incident.id)
    assert acked.status == "ACKNOWLEDGED"
    assert acked.acknowledged_at is not None

    resolved = await svc.resolve(incident.id)
    assert resolved.status == "RESOLVED"
    assert resolved.resolved_at is not None

    reopened = await svc.reopen(incident.id)
    assert reopened.status == "OPEN"

    subjects = [s for s, _ in fake_nats.published]
    assert "lokilinux.incidents.created" in subjects
    assert "lokilinux.incidents.updated" in subjects  # ack + reopen
    assert "lokilinux.incidents.resolved" in subjects


@pytest.mark.asyncio
async def test_illegal_transition_raises(db_session, fake_nats):
    host_id = "host-4"
    await _make_signal(db_session, host_id=host_id, sig_type="cpu.high")
    rule = await _make_rule(db_session)
    svc = IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH())
    incident = await svc.open_from_candidate(
        _candidate(rule, host_id=host_id, member_types=["cpu.high"], score=60, root_signal_type="cpu.high")
    )

    with pytest.raises(ValueError):
        # OPEN -> CLOSED isn't legal (must resolve first)
        await svc._transition(incident.id, "CLOSED")


@pytest.mark.asyncio
async def test_maybe_auto_resolve_false_when_signals_not_quiet(db_session, fake_nats):
    host_id = "host-5"
    await _make_signal(db_session, host_id=host_id, sig_type="cpu.high", status="OPEN")
    rule = await _make_rule(db_session)
    svc = IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH())
    incident = await svc.open_from_candidate(
        _candidate(rule, host_id=host_id, member_types=["cpu.high"], score=60, root_signal_type="cpu.high")
    )

    resolved = await svc.maybe_auto_resolve(incident.id)
    assert resolved is False


@pytest.mark.asyncio
async def test_maybe_auto_resolve_true_when_all_signals_quiet(db_session, fake_nats):
    host_id = "host-6"
    quiet_since = datetime.now(timezone.utc) - timedelta(seconds=700)
    sig = await _make_signal(db_session, host_id=host_id, sig_type="cpu.high", status="OPEN")
    rule = await _make_rule(db_session)
    svc = IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH())
    incident = await svc.open_from_candidate(
        _candidate(rule, host_id=host_id, member_types=["cpu.high"], score=60, root_signal_type="cpu.high")
    )

    # Mark the linked signal RESOLVED and quiet for long enough.
    sig.status = "RESOLVED"
    sig.last_seen = quiet_since
    await db_session.flush()

    resolved = await svc.maybe_auto_resolve(incident.id)
    assert resolved is True

    row = await db_session.get(Incident, incident.id)
    assert row.status == "RESOLVED"


@pytest.mark.asyncio
async def test_resolve_resolves_the_incident_alert_and_reopen_clears_resolved_at(db_session, fake_nats):
    await _make_signal(db_session, host_id="host-7", sig_type="cpu.high")
    rule = await _make_rule(db_session)
    candidate = _candidate(rule, host_id="host-7", member_types=["cpu.high"], score=60, root_signal_type="cpu.high")
    svc = IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH())
    incident = await svc.open_from_candidate(candidate)

    resolved = await svc.resolve(incident.id)
    alert = (await db_session.execute(select(Alert).where(Alert.incident_id == incident.id))).scalar_one()
    await db_session.refresh(alert)
    assert alert.status == "RESOLVED"
    assert resolved.resolved_at is not None

    reopened = await svc.reopen(incident.id)
    assert reopened.resolved_at is None


@pytest.mark.asyncio
async def test_already_resolved_signals_are_not_attached_to_a_new_incident(db_session, fake_nats):
    live = await _make_signal(db_session, host_id="host-8", sig_type="cpu.high")
    await _make_signal(db_session, host_id="host-8", sig_type="load.high", status="RESOLVED")
    rule = await _make_rule(db_session)
    candidate = _candidate(
        rule, host_id="host-8", member_types=["cpu.high", "load.high"], score=65, root_signal_type="cpu.high"
    )
    incident = await IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH()).open_from_candidate(candidate)

    links = (await db_session.execute(select(IncidentSignal).where(IncidentSignal.incident_id == incident.id))).scalars().all()
    assert [link.signal_id for link in links] == [live.id]


@pytest.mark.asyncio
async def test_a_suppressed_signal_counts_as_done_for_auto_resolve(db_session, fake_nats):
    host_id = "host-9"
    quiet = datetime.now(timezone.utc) - timedelta(seconds=700)
    sig = await _make_signal(db_session, host_id=host_id, sig_type="cpu.high", status="SUPPRESSED", last_seen=quiet)
    rule = await _make_rule(db_session)
    svc = IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH())
    incident = await svc.open_from_candidate(
        _candidate(rule, host_id=host_id, member_types=["cpu.high"], score=60, root_signal_type="cpu.high")
    )
    assert sig.id is not None

    assert await svc.maybe_auto_resolve(incident.id) is True


@pytest.mark.asyncio
async def test_reattach_writes_evidence_only_for_newly_linked_signals(db_session, fake_nats):
    host_id = "host-10"
    await _make_signal(db_session, host_id=host_id, sig_type="cpu.high")
    rule = await _make_rule(db_session)
    ch = _FakeCH()
    svc = IncidentService(db_session, fake_nats, _FakeCache(), ch)
    candidate = _candidate(
        rule, host_id=host_id, member_types=["cpu.high"], score=60, root_signal_type="cpu.high", group_key="g-10"
    )
    await svc.open_from_candidate(candidate)
    assert len(ch.inserted) == 1  # created: one batched insert for its signals

    await svc.open_from_candidate(candidate)  # window re-fires, nothing new to link
    assert len(ch.inserted) == 1

    await _make_signal(db_session, host_id=host_id, sig_type="load.high")
    both = _candidate(
        rule, host_id=host_id, member_types=["cpu.high", "load.high"], score=65,
        root_signal_type="cpu.high", group_key="g-10",
    )
    await svc.open_from_candidate(both)
    assert len(ch.inserted) == 2
    assert [row[4] for row in ch.inserted[1][1]] == [fingerprint("default", host_id, "load.high", None)]


@pytest.mark.asyncio
async def test_member_lookup_finds_a_signal_whose_fingerprint_carries_a_resource(db_session, fake_nats):
    from lokilinux.models.agent import Agent, AgentStatus

    agent = Agent(agent_id=str(uuid4()), status=AgentStatus.ACTIVE, hostname="web-01")
    db_session.add(agent)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    # job.failed keyed on its service: the fingerprint differs from fingerprint(tenant, host, type, None)
    sig = Signal(
        tenant_id="default", type="job.failed", severity="HIGH", status="OPEN", host_id=agent.id,
        service="backup", fingerprint=fingerprint("default", str(agent.id), "job.failed", "backup"),
        first_seen=now, last_seen=now,
    )
    db_session.add(sig)
    await db_session.flush()
    rule = await _make_rule(db_session, conditions=[{"signal": "job.failed", "weight": 60}])
    candidate = _candidate(
        rule, host_id=str(agent.id), member_types=["job.failed"], score=60, root_signal_type="job.failed"
    )

    incident = await IncidentService(db_session, fake_nats, _FakeCache(), _FakeCH()).open_from_candidate(candidate)

    links = (await db_session.execute(select(IncidentSignal).where(IncidentSignal.incident_id == incident.id))).scalars().all()
    assert [link.signal_id for link in links] == [sig.id]
