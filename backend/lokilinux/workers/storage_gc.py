"""
LokiLinux — StorageGCWorker: sweeps orphan objects from the bucket.

An object in the bucket with no live storage_objects row is garbage: either
the upload died before its row was written, or the row was deleted while the
blob survived (a failed S3 delete — the delete path marks the row DELETED
first, so a surviving blob always has a DELETED row or none at all).

Objects younger than the grace period are never touched: an upload writes the
blob first and the row second, so a fresh blob may legitimately have no row
yet.

Runs on its own loop (same shape as RetentionCleanupWorker — nothing marks
"time to collect garbage"). Sweeps once per hour.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from lokilinux.models.storage_object import StorageObject
from lokilinux.object_storage import ObjectStorage
from lokilinux.services.storage_service import CATEGORIES

logger = structlog.get_logger()

_SWEEP_INTERVAL_SECONDS = 3600
# A blob younger than this may still be waiting for its row to be written.
_GRACE_SECONDS = 3600
# Upper bound per prefix per sweep — the next sweep picks up the rest.
_MAX_KEYS_PER_PREFIX = 10000


class StorageGCWorker:
    def __init__(self, db_session_factory, storage: ObjectStorage) -> None:
        self._db_factory = db_session_factory
        self._storage = storage
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("StorageGCWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._sweep()
            except Exception:
                logger.error("storage_gc.sweep_failed", exc_info=True)
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)

    async def _sweep(self) -> None:
        live_keys, deleted_keys = await self._known_keys()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=_GRACE_SECONDS)
        deleted = 0
        scanned = 0
        for prefix in sorted(set(CATEGORIES.values())):
            for obj in await self._storage.list(prefix, max_keys=_MAX_KEYS_PER_PREFIX):
                scanned += 1
                if obj.key in live_keys:
                    continue
                # A DELETED row's blob is garbage too — it survived the delete.
                if obj.key not in deleted_keys and not self._older_than(obj.last_modified, cutoff):
                    continue
                try:
                    await self._storage.delete(obj.key)
                except Exception:
                    logger.error("storage_gc.delete_failed", object_key=obj.key, exc_info=True)
                    continue
                deleted += 1
                logger.info("storage_gc.orphan_deleted", object_key=obj.key)
        if deleted:
            logger.info("storage_gc.sweep_done", scanned=scanned, deleted=deleted)

    async def _known_keys(self) -> tuple[set[str], set[str]]:
        """(keys with a live row, keys whose row is DELETED)."""
        live: set[str] = set()
        gone: set[str] = set()
        async with self._db_factory() as db:
            result = await db.execute(select(StorageObject.object_key, StorageObject.status))
            for key, status in result.all():
                if status == "DELETED":
                    gone.add(key)
                else:
                    live.add(key)
        return live, gone

    @staticmethod
    def _older_than(last_modified: datetime | None, cutoff: datetime) -> bool:
        if last_modified is None:
            return True
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        return last_modified < cutoff
