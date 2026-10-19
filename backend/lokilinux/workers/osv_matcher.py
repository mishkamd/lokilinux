"""
LokiLinux — OsvMatcherWorker: periodic Debian/Ubuntu CVE matching (ROADMAP R4).

Own asyncio loop, like RetentionCleanupWorker. Each tick runs the full match
in services/osv_matcher.py. A failed tick is logged and retried on the next
one, so an OSV outage doesn't stop the worker.
"""

import asyncio

import httpx
import structlog

from lokilinux.services.osv_matcher import match_packages

logger = structlog.get_logger()


class OsvMatcherWorker:
    def __init__(self, db_session_factory, base_url: str, interval_sec: int) -> None:  # type: ignore[no-untyped-def]
        self.db_factory = db_session_factory
        self.base_url = base_url
        self.interval_sec = interval_sec
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("OsvMatcherWorker started", interval_sec=self.interval_sec)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.error("osv_matcher.tick_failed", exc_info=True)
            await asyncio.sleep(self.interval_sec)

    async def run_once(self) -> int:
        async with self.db_factory() as db, httpx.AsyncClient(timeout=30.0) as client:
            written = await match_packages(db, client, base_url=self.base_url)
        logger.info("osv_matcher.tick_done", rows=written)
        return written
