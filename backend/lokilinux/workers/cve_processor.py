"""
LokiLinux — CVEProcessorWorker: NATS consumer for CVE database update events.

Subscribes to lokilinux.cve.database.updated.
On update: invalidates all CVE-related cache keys so next read fetches fresh data.
"""

import logging

from lokilinux.nats_topics import CVE_DATABASE_UPDATED

logger = logging.getLogger(__name__)


class CVEProcessorWorker:
    def __init__(self, nats_client, db_session_factory, cache) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache

    async def start(self) -> None:
        await self.nats.subscribe(CVE_DATABASE_UPDATED, cb=self._handle_update)
        logger.info("CVEProcessorWorker started")

    async def _handle_update(self, msg) -> None:
        # ponytail: full NVD import in Phase 3; invalidate stale cache now
        logger.info("CVE database update received — invalidating cache")
        await self.cache.invalidate_cve_database()
