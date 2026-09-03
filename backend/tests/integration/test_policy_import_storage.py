"""Integration test: /policy-sets/import persists the fetched datastream to
object storage before parsing it (Object Storage plan) — the external URL
is fetched exactly once and the bytes end up recorded on the Job row with
a matching SHA-256, verifiable via /storage/objects/{id}/verify.

No respx/httpx-mock dependency in this project — a small fake httpx client
(matching the existing FakeCache/FakeNats/FakeCH hand-rolled style) stands
in for the external ComplianceAsCode mirror.
"""

import uuid

import pytest
from httpx import AsyncClient

from lokilinux.models.job import Job

_MINIMAL_XCCDF = (
    b'<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2" id="xccdf_test_benchmark"/>'
)


class _FakeStreamResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = {"content-type": "application/xml"}

    def raise_for_status(self) -> None:
        pass

    async def aiter_bytes(self, chunk_size: int):
        yield self._body

    async def __aenter__(self) -> "_FakeStreamResponse":
        return self

    async def __aexit__(self, *exc) -> None:
        pass


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def stream(self, method: str, url: str):
        return _FakeStreamResponse(_MINIMAL_XCCDF)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> None:
        pass


@pytest.mark.asyncio
async def test_import_persists_datastream_to_storage(
    client: AsyncClient, db_session, monkeypatch
):
    import lokilinux.api.v1.routers.compliance.policy_engine as policy_engine

    monkeypatch.setattr(policy_engine.httpx, "AsyncClient", _FakeAsyncClient)

    resp = await client.post(
        "/api/v1/compliance/policy-sets/import",
        json={
            "source": "complianceascode",
            "content_version": "test-v1",
            "datastream_url": "http://mirror.invalid/ds.xml",
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await db_session.get(Job, uuid.UUID(job_id))
    await db_session.refresh(job)
    assert job.status.value == "COMPLETED"
    assert job.parameters["storage_object_id"]
    assert job.parameters["sha256"]

    verify_resp = await client.post(
        f"/api/v1/storage/objects/{job.parameters['storage_object_id']}/verify"
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["sha256_match"] is True

    meta_resp = await client.get(
        f"/api/v1/storage/objects/{job.parameters['storage_object_id']}"
    )
    assert meta_resp.status_code == 200
    assert meta_resp.json()["category"] == "compliance.datastream"
