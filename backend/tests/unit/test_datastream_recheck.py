"""The datastream fetch re-checks the SSRF guard in the background task (ROADMAP P1r-2).

The endpoint checks datastream_url before queuing the job, but DNS can change while
the job waits, so _run_compliance_import must refuse again before opening a client.
"""

import contextlib
import uuid
from types import SimpleNamespace

import lokilinux.api.v1.routers.compliance.policy_engine as policy_engine
from lokilinux.models.job import JobStatus


class _FakeDB:
    def __init__(self, job) -> None:
        self._job = job
        self.commits = 0

    async def execute(self, _stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self._job)

    async def commit(self) -> None:
        self.commits += 1


async def test_unsafe_datastream_url_refused_before_fetch(monkeypatch):
    fetches = []

    class _NoFetchClient:
        def __init__(self, *args, **kwargs) -> None:
            fetches.append(args)
            raise AssertionError("fetched a datastream the SSRF guard should refuse")

    # Only policy_engine's reference is replaced, not the global httpx module.
    monkeypatch.setattr(policy_engine, "httpx", SimpleNamespace(AsyncClient=_NoFetchClient))

    job = SimpleNamespace(
        id=uuid.uuid4(),
        status=JobStatus.QUEUED,
        started_at=None,
        completed_at=None,
        parameters={},
    )
    db = _FakeDB(job)

    @contextlib.asynccontextmanager
    async def session_factory():
        yield db

    await policy_engine._run_compliance_import(
        session_factory, object(), job.id, "http://127.0.0.1/x", "test-v1", None
    )

    assert fetches == []
    assert job.status == JobStatus.FAILED
    # The task's catch-all swallows the fake's AssertionError, so the error text is
    # what shows the guard ran and refused, rather than the fetch being skipped by luck.
    assert "resolves to a blocked address" in job.parameters["error"]
