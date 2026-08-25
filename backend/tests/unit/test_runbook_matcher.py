import contextlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

import lokilinux.runbooks.service as runbook_service
from lokilinux.models.workflow import Workflow
from lokilinux.runbooks.models import Runbook
from lokilinux.runbooks.service import execute_runbook, find_matching_runbooks, maybe_auto_run
from lokilinux.workers.incident_worker import IncidentWorker


async def _make_workflow(db_session) -> Workflow:
    wf = Workflow(name=f"wf-{uuid4()}", slug=f"wf-{uuid4()}")
    db_session.add(wf)
    await db_session.flush()
    return wf


async def _make_runbook(db_session, *, with_workflow: bool = False, **overrides) -> Runbook:
    workflow_id = overrides.pop("workflow_id", None)
    if with_workflow and workflow_id is None:
        workflow_id = (await _make_workflow(db_session)).id
    base = dict(
        tenant_id="default", name=f"runbook-{uuid4()}", incident_type="application_degradation",
        workflow_id=workflow_id, trigger_mode="MANUAL", min_severity="HIGH", enabled=True,
    )
    base.update(overrides)
    rb = Runbook(**base)
    db_session.add(rb)
    await db_session.flush()
    return rb


# ── find_matching_runbooks ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_matches_by_incident_type(db_session):
    matching = await _make_runbook(db_session, incident_type="application_degradation")
    await _make_runbook(db_session, incident_type="something_else")

    results = await find_matching_runbooks(db_session, "application_degradation", "CRITICAL")
    assert [r.id for r in results] == [matching.id]


@pytest.mark.asyncio
async def test_disabled_runbooks_are_excluded(db_session):
    await _make_runbook(db_session, incident_type="application_degradation", enabled=False)
    results = await find_matching_runbooks(db_session, "application_degradation", "CRITICAL")
    assert results == []


@pytest.mark.asyncio
async def test_severity_below_min_severity_is_excluded(db_session):
    await _make_runbook(db_session, incident_type="application_degradation", min_severity="CRITICAL")
    results = await find_matching_runbooks(db_session, "application_degradation", "HIGH")
    assert results == []


@pytest.mark.asyncio
async def test_severity_at_or_above_min_severity_matches(db_session):
    rb = await _make_runbook(db_session, incident_type="application_degradation", min_severity="HIGH")
    results = await find_matching_runbooks(db_session, "application_degradation", "CRITICAL")
    assert [r.id for r in results] == [rb.id]


# ── execute_runbook ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_runbook_without_workflow_id_raises(db_session):
    rb = await _make_runbook(db_session, workflow_id=None)
    with pytest.raises(ValueError):
        await execute_runbook(db_session, cache=None, runbook=rb)


@pytest.mark.asyncio
async def test_execute_runbook_calls_start_run(db_session, monkeypatch):
    calls = []

    async def _fake_start_run(db, cache, workflow_id, *, trigger_type, triggered_by, nats=None, **kw):
        calls.append((workflow_id, trigger_type, triggered_by))
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(runbook_service, "start_run", _fake_start_run)
    workflow_id = (await _make_workflow(db_session)).id
    rb = await _make_runbook(db_session, workflow_id=workflow_id)

    run = await execute_runbook(db_session, cache=None, runbook=rb)

    assert run is not None
    assert calls == [(workflow_id, "API", None)]


# ── maybe_auto_run ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_auto_run_skips_manual_runbooks(db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(runbook_service, "execute_runbook", _recording_execute(calls))
    await _make_runbook(db_session, trigger_mode="MANUAL", with_workflow=True)

    await maybe_auto_run(db_session, cache=None, incident_type="application_degradation", incident_severity="CRITICAL", autorun_enabled=True)
    assert calls == []


@pytest.mark.asyncio
async def test_maybe_auto_run_skips_when_kill_switch_off(db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(runbook_service, "execute_runbook", _recording_execute(calls))
    await _make_runbook(db_session, trigger_mode="AUTO", with_workflow=True)

    await maybe_auto_run(db_session, cache=None, incident_type="application_degradation", incident_severity="CRITICAL", autorun_enabled=False)
    assert calls == []


@pytest.mark.asyncio
async def test_maybe_auto_run_executes_auto_runbooks_when_enabled(db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(runbook_service, "execute_runbook", _recording_execute(calls))
    rb = await _make_runbook(db_session, trigger_mode="AUTO", with_workflow=True)

    await maybe_auto_run(db_session, cache=None, incident_type="application_degradation", incident_severity="CRITICAL", autorun_enabled=True)
    assert [r.id for r in calls] == [rb.id]


@pytest.mark.asyncio
async def test_maybe_auto_run_continues_after_one_failure(db_session, monkeypatch):
    async def _failing_execute(db, cache, runbook, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(runbook_service, "execute_runbook", _failing_execute)
    await _make_runbook(db_session, trigger_mode="AUTO", with_workflow=True)

    runs = await maybe_auto_run(db_session, cache=None, incident_type="application_degradation", incident_severity="CRITICAL", autorun_enabled=True)
    assert runs == []  # failure caught, not raised


def _recording_execute(calls):
    async def _execute(db, cache, runbook, **kw):
        calls.append(runbook)
        return SimpleNamespace(id=uuid4())

    return _execute


# ── IncidentWorker matcher hook ───────────────────────────────────────────────


def _db_factory(db_session):
    @contextlib.asynccontextmanager
    async def factory():
        yield db_session

    return factory


def _msg(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps(payload).encode())


@pytest.mark.asyncio
async def test_incident_created_handler_respects_kill_switch(db_session, fake_cache, fake_nats, monkeypatch):
    calls = []
    monkeypatch.setattr(runbook_service, "execute_runbook", _recording_execute(calls))
    await _make_runbook(db_session, trigger_mode="AUTO", with_workflow=True, incident_type="application_degradation")

    worker = IncidentWorker(fake_nats, _db_factory(db_session), fake_cache, None)
    await worker._handle_incident_created(_msg({"type": "application_degradation", "severity": "CRITICAL"}))

    assert calls == []  # kill switch defaults False, no Setting row overriding it


@pytest.mark.asyncio
async def test_incident_created_handler_malformed_json_does_not_raise(db_session, fake_cache, fake_nats):
    worker = IncidentWorker(fake_nats, _db_factory(db_session), fake_cache, None)
    await worker._handle_incident_created(SimpleNamespace(data=b"{not-json"))
