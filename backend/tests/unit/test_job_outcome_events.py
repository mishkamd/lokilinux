import json

import pytest

from lokilinux.api.grpc.agent_service import _emit_job_outcomes


class _Nats:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, json.loads(payload)))


@pytest.mark.asyncio
async def test_failed_and_completed_jobs_become_events_others_are_skipped():
    nats = _Nats()
    results = [
        {"job_id": "j-ok", "state": 2, "exit_code": 0},
        {"job_id": "j-bad", "state": 3, "exit_code": 1},
        {"job_id": "j-timeout", "state": 4, "exit_code": None},
        {"job_id": "j-running", "state": 1},
        {"job_id": "j-cancelled", "state": 5},
        {"state": 3},  # no job_id
    ]
    await _emit_job_outcomes(nats, "host-1", results)

    assert [(s, p["type"], p["payload"]["job_id"]) for s, p in nats.published] == [
        ("lokilinux.events.raw.job", "job.completed", "j-ok"),
        ("lokilinux.events.raw.job", "job.failed", "j-bad"),
        ("lokilinux.events.raw.job", "job.failed", "j-timeout"),
    ]
    assert all(p["host_id"] == "host-1" for _, p in nats.published)


@pytest.mark.asyncio
async def test_a_repeated_result_gets_the_same_event_id():
    nats = _Nats()
    await _emit_job_outcomes(nats, "host-1", [{"job_id": "j1", "state": 3}])
    await _emit_job_outcomes(nats, "host-1", [{"job_id": "j1", "state": 3}])
    assert nats.published[0][1]["event_id"] == nats.published[1][1]["event_id"]
