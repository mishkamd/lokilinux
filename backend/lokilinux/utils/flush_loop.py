"""
LokiLinux — periodic drain for the batched ClickHouse writers.

The repositories only flush when add() is called, so the last rows of a quiet
period would sit in memory until the next event (or be lost on a restart).
Each tick also records a liveness beat for the owning worker.
"""

import asyncio
from collections.abc import Awaitable, Callable

import structlog

from lokilinux.utils import liveness

logger = structlog.get_logger()


async def flush_loop(flush: Callable[[], Awaitable[None]], interval: float, worker: str) -> None:
    while True:
        await asyncio.sleep(interval)
        liveness.beat(worker)
        try:
            await flush()
        except Exception:
            logger.error("flush_loop.failed", worker=worker, exc_info=True)
