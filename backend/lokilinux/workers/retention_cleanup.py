"""
LokiLinux — RetentionCleanupWorker: periodic audit-log purge.

Runs its own asyncio loop (same shape as HeartbeatMonitorWorker — no NATS
event marks "time to clean up"). Deletes audit_logs rows older than
security.audit_log_retention_days. Sweeps once per hour; a purge job doesn't
need per-minute precision.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete

from lokilinux.models.audit import AuditLog
from lokilinux.settings_schema import get_setting_value

logger = structlog.get_logger()

_SWEEP_INTERVAL_SECONDS = 3600


class RetentionCleanupWorker:
    def __init__(self, db_session_factory) -> None:
        self.db_factory = db_session_factory
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("RetentionCleanupWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._purge()
            except Exception:
                logger.error("retention_cleanup.purge_failed", exc_info=True)
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)

    async def _purge(self) -> None:
        async with self.db_factory() as db:
            retention_days = await get_setting_value(db, "security.audit_log_retention_days")
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            result = await db.execute(delete(AuditLog).where(AuditLog.timestamp < cutoff))
            await db.commit()
            if result.rowcount:
                logger.info("audit_log.purged", rows=result.rowcount, cutoff=str(cutoff))
