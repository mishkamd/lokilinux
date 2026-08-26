import contextlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lokilinux.events.fingerprint import fingerprint
from lokilinux.incidents.models import Incident, IncidentSignal
from lokilinux.signals.models import Signal
from lokilinux.workers.incident_worker import IncidentWorker


class _FakeCache:
    async def set_nx(self, key: str, ttl: int) -> bool:
        return True


class _FakeCH:
    async def insert(self, table, data, column_names) -> None:
        pass


def _db_factory(db_session):
    @contextlib.asynccontextmanager
    async def factory():
        yield db_session

    return factory


def _msg(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps(payload).encode())


async def _make_open_incident_with_signal(db_session, *, host_id: str, sig_type: str, quiet: bool) -> tuple[Incident, Signal]:
    now = datetime.now(timezone.utc)
    last_seen = now - timedelta(seconds=700) if quiet else now
    sig = Signal(
        tenant_id="default", type=sig_type, severity="HIGH",
        status="RESOLVED" if quiet else "OPEN",
        fingerprint=fingerprint("default", host_id, sig_type, None),
        first_seen=now, last_seen=last_seen,
    )
    db_session.add(sig)
    await db_session.flush()

    incident = Incident(
        tenant_id="default", title="t", type="application_degradation", severity="CRITICAL",
        status="OPEN", group_key=str(uuid4()),
    )
    db_session.add(incident)
    await db_session.flush()
    db_session.add(IncidentSignal(incident_id=incident.id, signal_id=sig.id))
    await db_session.flush()
    return incident, sig


@pytest.mark.asyncio
async def test_sweep_resolves_incident_with_quiet_signals(db_session, fake_nats):
    incident, _ = await _make_open_incident_with_signal(db_session, host_id="host-1", sig_type="cpu.high", quiet=True)
    worker = IncidentWorker(fake_nats, _db_factory(db_session), _FakeCache(), _FakeCH())

    await worker._sweep()

    row = await db_session.get(Incident, incident.id)
    assert row.status == "RESOLVED"


@pytest.mark.asyncio
async def test_sweep_leaves_incident_open_when_signal_not_quiet(db_session, fake_nats):
    incident, _ = await _make_open_incident_with_signal(db_session, host_id="host-2", sig_type="cpu.high", quiet=False)
    worker = IncidentWorker(fake_nats, _db_factory(db_session), _FakeCache(), _FakeCH())

    await worker._sweep()

    row = await db_session.get(Incident, incident.id)
    assert row.status == "OPEN"


@pytest.mark.asyncio
async def test_sweep_with_no_open_incidents_is_a_noop(db_session, fake_nats):
    worker = IncidentWorker(fake_nats, _db_factory(db_session), _FakeCache(), _FakeCH())
    await worker._sweep()  # must not raise


@pytest.mark.asyncio
async def test_signal_resolved_watcher_triggers_check_but_quiet_gate_still_applies(db_session, fake_nats):
    """The watcher fires the instant a signal resolves — at that moment
    last_seen is "now", so the 600s quiet gate keeps the incident OPEN.
    Resolution only happens later, via the sweep."""
    incident, sig = await _make_open_incident_with_signal(db_session, host_id="host-3", sig_type="cpu.high", quiet=False)
    worker = IncidentWorker(fake_nats, _db_factory(db_session), _FakeCache(), _FakeCH())

    await worker._handle_signal_resolved(_msg({"fingerprint": sig.fingerprint}))

    row = await db_session.get(Incident, incident.id)
    assert row.status == "OPEN"  # not quiet long enough yet


@pytest.mark.asyncio
async def test_signal_resolved_for_unknown_fingerprint_is_a_noop(db_session, fake_nats):
    worker = IncidentWorker(fake_nats, _db_factory(db_session), _FakeCache(), _FakeCH())
    await worker._handle_signal_resolved(_msg({"fingerprint": "does-not-exist"}))  # must not raise


@pytest.mark.asyncio
async def test_malformed_json_does_not_raise(db_session, fake_nats):
    worker = IncidentWorker(fake_nats, _db_factory(db_session), _FakeCache(), _FakeCH())
    await worker._handle_signal_resolved(SimpleNamespace(data=b"{not-json"))
