"""
LokiLinux — batched ClickHouse writer for signal_occurrences.

Simpler than events/repository.py's EventRepository: signal occurrences are
already pre-filtered to "something a detector considered significant" — far
lower volume than the raw event firehose, and without a DEBUG/INFO/ERROR
severity spread to prioritize drops against. So on sustained overflow this
just drops the oldest buffered rows (FIFO), no severity tiering.
"""

from datetime import datetime
from typing import Any
import asyncio
import json
import time

import structlog

from lokilinux.ch import ClickHouseStore
from lokilinux.metrics import clickhouse_insert_errors_total, event_buffer_depth

logger = structlog.get_logger()

OCCURRENCE_INSERT_BATCH = 500
OCCURRENCE_INSERT_FLUSH_SEC = 2.0
OCCURRENCE_BUFFER_MAX = 5000

_COLUMNS = ["timestamp", "tenant", "signal_type", "severity", "host_id", "service", "fingerprint", "value", "metadata"]


class SignalOccurrenceRepository:
    def __init__(self, ch: ClickHouseStore) -> None:
        self.ch = ch
        self._buffer: list[list[Any]] = []
        self._oldest_buffered_at: float | None = None
        self._lock = asyncio.Lock()

    async def add(
        self, *, timestamp: datetime, tenant_id: str, signal_type: str, severity: str,
        host_id: str | None, service: str | None, fingerprint: str, value: float,
        metadata: dict[str, Any],
    ) -> None:
        row = [
            timestamp, tenant_id, signal_type, severity, host_id or "", service or "",
            fingerprint, value, json.dumps(metadata, default=str),
        ]
        async with self._lock:
            self._buffer.append(row)
            if self._oldest_buffered_at is None:
                self._oldest_buffered_at = time.monotonic()
            should_flush = (
                len(self._buffer) >= OCCURRENCE_INSERT_BATCH
                or (time.monotonic() - self._oldest_buffered_at) > OCCURRENCE_INSERT_FLUSH_SEC
            )
            event_buffer_depth.labels(buffer="signal_occurrences").set(len(self._buffer))
        if should_flush:
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            batch, self._buffer = self._buffer, []
            self._oldest_buffered_at = None
            event_buffer_depth.labels(buffer="signal_occurrences").set(0)
        try:
            await self.ch.insert("signal_occurrences", batch, column_names=_COLUMNS)
        except Exception:
            logger.error("signal_occurrences.flush_failed", batch_size=len(batch), exc_info=True)
            clickhouse_insert_errors_total.labels(table="signal_occurrences").inc()
            async with self._lock:
                self._buffer = batch + self._buffer
                if self._oldest_buffered_at is None:
                    self._oldest_buffered_at = time.monotonic()
                overflow = len(self._buffer) - OCCURRENCE_BUFFER_MAX
                if overflow > 0:
                    dropped = self._buffer[:overflow]
                    self._buffer = self._buffer[overflow:]
                    logger.warning("signal_occurrences.buffer_overflow_dropped", dropped=len(dropped))
                event_buffer_depth.labels(buffer="signal_occurrences").set(len(self._buffer))
