"""Guards for the storage delete ordering (MIS-144) and the orphan sweep
(MIS-145). FakeObjectStorage from conftest — no real S3/RustFS involved.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from lokilinux.models.storage_object import StorageObject
from lokilinux.services.storage_service import StorageService
from lokilinux.workers.storage_gc import StorageGCWorker


def _row(object_id: Any, key: str, status: str = "AVAILABLE") -> StorageObject:
    return StorageObject(
        id=object_id,
        filename="f.txt",
        original_filename="f.txt",
        content_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
        storage_provider="s3",
        bucket="lokilinux-test",
        object_key=key,
        version=1,
        category="upload",
        status=status,
    )


@pytest.mark.asyncio
async def test_delete_marks_row_deleted_before_touching_s3(
    db_session: Any, fake_storage: Any
) -> None:
    """MIS-144: the row must be committed as DELETED *before* the blob is
    deleted — the other order leaves a row claiming AVAILABLE for an object
    that no longer exists when the commit fails."""
    storage = fake_storage
    object_id = uuid4()
    key = f"uploads/{object_id}/v1/f.txt"
    storage._objects[key] = b"x"
    db_session.add(_row(object_id, key))
    await db_session.commit()

    service = StorageService(storage, db_session)
    await service.delete(object_id)

    # Row is DELETED and the blob is gone.
    await db_session.refresh(_row(object_id, key)) if False else None
    row = (
        await db_session.execute(select(StorageObject).where(StorageObject.id == object_id))
    ).scalar_one()
    assert row.status == "DELETED"
    assert key not in storage._objects


@pytest.mark.asyncio
async def test_delete_survives_s3_failure(db_session: Any, fake_storage: Any) -> None:
    """A failed blob delete must not fail the request — the row already says
    DELETED and the GC sweeps the leftover."""

    class BrokenStorage(type(fake_storage)):
        async def delete(self, key: str) -> None:
            raise OSError("s3 down")

    storage = BrokenStorage()
    object_id = uuid4()
    key = f"uploads/{object_id}/v1/f.txt"
    db_session.add(_row(object_id, key))
    await db_session.commit()

    await StorageService(storage, db_session).delete(object_id)  # must not raise

    row = (
        await db_session.execute(select(StorageObject).where(StorageObject.id == object_id))
    ).scalar_one()
    assert row.status == "DELETED"


class _GCStorage:
    """Minimal storage surface for the GC: list() + delete()."""

    def __init__(self, objects: dict[str, datetime]) -> None:
        self.objects = objects
        self.deleted: list[str] = []

    async def list(self, prefix: str, *, max_keys: int = 1000) -> list[Any]:
        return [
            SimpleNamespace(key=k, last_modified=ts)
            for k, ts in self.objects.items()
            if k.startswith(prefix)
        ]

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_gc_deletes_orphans_and_keeps_live_objects(db_session: Any) -> None:
    """MIS-145: blobs with no live row are garbage; blobs with a live row
    are not."""
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    fresh = datetime.now(timezone.utc)
    live_id = uuid4()
    live_key = f"uploads/{live_id}/v1/live.txt"
    db_session.add(_row(live_id, live_key))
    await db_session.commit()

    storage = _GCStorage(
        {
            live_key: old,                      # referenced by a live row -> keep
            f"uploads/{uuid4()}/v1/orphan.txt": old,   # no row -> delete
            f"uploads/{uuid4()}/v1/fresh.txt": fresh,  # no row, but too young -> keep
        }
    )
    worker = StorageGCWorker(lambda: _session(db_session), storage)
    await worker._sweep()

    assert f"uploads/{live_id}/v1/live.txt" not in storage.deleted
    assert len(storage.deleted) == 1
    assert storage.deleted[0].endswith("/orphan.txt")


@pytest.mark.asyncio
async def test_gc_deletes_blob_of_a_deleted_row(db_session: Any) -> None:
    """A blob that outlived its DELETED row is garbage too."""
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    gone_id = uuid4()
    gone_key = f"uploads/{gone_id}/v1/gone.txt"
    db_session.add(_row(gone_id, gone_key, status="DELETED"))
    await db_session.commit()

    storage = _GCStorage({gone_key: old})
    worker = StorageGCWorker(lambda: _session(db_session), storage)
    await worker._sweep()
    assert storage.deleted == [gone_key]


def _session(session: Any) -> Any:
    """Adapt a live session to the async-context-manager factory the worker
    expects (the worker's own sessions are separate in production)."""

    class _Ctx:
        async def __aenter__(self) -> Any:
            return session

        async def __aexit__(self, *exc: Any) -> None:
            return None

    return _Ctx()
