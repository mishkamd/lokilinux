import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from lokilinux.models.audit import AuditLog
from lokilinux.workers import retention_cleanup as module
from lokilinux.workers.retention_cleanup import RetentionCleanupWorker


def _db_factory(db_session):
    @contextlib.asynccontextmanager
    async def factory():
        yield db_session

    return factory


@pytest.mark.asyncio
async def test_purge_deletes_all_old_rows_across_several_batches_and_keeps_recent(
    db_session, monkeypatch
):
    monkeypatch.setattr(module, "_PURGE_BATCH", 2)
    monkeypatch.setattr(module, "_PURGE_PAUSE_SECONDS", 0)
    old = datetime.now(timezone.utc) - timedelta(days=3650)
    db_session.add_all([AuditLog(action="old", timestamp=old) for _ in range(5)])
    db_session.add(AuditLog(action="recent", timestamp=datetime.now(timezone.utc)))
    await db_session.commit()

    await RetentionCleanupWorker(_db_factory(db_session))._purge()

    remaining = (await db_session.execute(select(AuditLog.action))).scalars().all()
    assert remaining == ["recent"]
