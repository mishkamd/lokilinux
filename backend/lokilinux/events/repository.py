"""
LokiLinux — batched ClickHouse writer + cursor query for the `events` table.

Producers never write ClickHouse directly. EventProcessorWorker (Task A5) is
the only caller of add() — batching column-oriented inserts is what keeps CH
ingest cheap; per-row inserts fall over well before the volumes this pipeline
targets.

Cursor convention matches the rest of the API (see routers/jobs.py): the
router owns encode_cursor/decode_cursor, this repository only ever sees an
already-decoded (timestamp, event_id) keyset pair.
"""

from datetime import datetime
from typing import Any
import asyncio
import json
import time

import structlog

from lokilinux.ch import ClickHouseStore
from lokilinux.events.schemas import NormalizedEvent
from lokilinux.metrics import events_dropped_total

logger = structlog.get_logger()

EVENT_INSERT_BATCH = 1000
EVENT_INSERT_FLUSH_SEC = 1.0
EVENT_BUFFER_MAX = 10_000

# Severity index within a buffered row — kept in sync with _COLUMNS below.
_SEVERITY_COL = 5
_NEVER_DROP = {"ERROR", "CRITICAL"}
_DROP_PRIORITY = {"DEBUG": 0, "INFO": 1, "WARNING": 2}

_COLUMNS = [
    "timestamp", "event_id", "tenant", "source", "type", "severity",
    "host_id", "service", "fingerprint", "schema_version", "payload",
]


def _row(event: NormalizedEvent) -> list[Any]:
    return [
        event.timestamp, str(event.event_id), event.tenant_id, event.source, event.type,
        event.severity, event.host_id or "", event.service or "", event.fingerprint,
        event.schema_version, json.dumps(event.payload, default=str),
    ]


class EventRepository:
    """In-memory buffer in front of ClickHouse — flush on size or age."""

    def __init__(self, ch: ClickHouseStore) -> None:
        self.ch = ch
        self._buffer: list[list[Any]] = []
        self._oldest_buffered_at: float | None = None
        self._lock = asyncio.Lock()

    async def add(self, event: NormalizedEvent) -> None:
        async with self._lock:
            self._buffer.append(_row(event))
            if self._oldest_buffered_at is None:
                self._oldest_buffered_at = time.monotonic()
            should_flush = (
                len(self._buffer) >= EVENT_INSERT_BATCH
                or (time.monotonic() - self._oldest_buffered_at) > EVENT_INSERT_FLUSH_SEC
            )
        if should_flush:
            await self.flush()

    async def flush(self) -> None:
        """Drain the buffer in one column-oriented insert. Safe to call with
        an empty buffer (no-op) — used both by add()'s triggers and by
        callers that want to force a drain (e.g. worker shutdown)."""
        async with self._lock:
            if not self._buffer:
                return
            batch, self._buffer = self._buffer, []
            self._oldest_buffered_at = None
        try:
            await self.ch.insert("events", batch, column_names=_COLUMNS)
        except Exception:
            logger.error("events.flush_failed", batch_size=len(batch), exc_info=True)
            await self._requeue_with_backpressure(batch)

    async def _requeue_with_backpressure(self, failed_batch: list[list[Any]]) -> None:
        async with self._lock:
            self._buffer = failed_batch + self._buffer
            if self._oldest_buffered_at is None:
                self._oldest_buffered_at = time.monotonic()
            overflow = len(self._buffer) - EVENT_BUFFER_MAX
            if overflow <= 0:
                return
            # Oldest DEBUG/INFO first, then WARNING — ERROR/CRITICAL never drop.
            droppable = sorted(
                (i for i, row in enumerate(self._buffer) if row[_SEVERITY_COL] not in _NEVER_DROP),
                key=lambda i: (_DROP_PRIORITY.get(self._buffer[i][_SEVERITY_COL], 99), i),
            )
            to_drop = set(droppable[:overflow])
            if not to_drop:
                return
            self._buffer = [row for i, row in enumerate(self._buffer) if i not in to_drop]
            events_dropped_total.labels(reason="buffer_overflow").inc(len(to_drop))
            logger.warning("events.buffer_overflow_dropped", dropped=len(to_drop))

    async def query(
        self,
        tenant_id: str,
        *,
        type: str | None = None,
        source: str | None = None,
        host_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        before: tuple[datetime, str] | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 200))
        conditions = ["tenant = %(tenant)s"]
        params: dict[str, Any] = {"tenant": tenant_id}
        if type:
            conditions.append("type = %(type)s")
            params["type"] = type
        if source:
            conditions.append("source = %(source)s")
            params["source"] = source
        if host_id:
            conditions.append("host_id = %(host_id)s")
            params["host_id"] = host_id
        if since:
            conditions.append("timestamp >= %(since)s")
            params["since"] = since
        if until:
            conditions.append("timestamp <= %(until)s")
            params["until"] = until
        if before:
            before_ts, before_id = before
            conditions.append("(timestamp, event_id) < (%(before_ts)s, %(before_id)s)")
            params["before_ts"] = before_ts
            params["before_id"] = before_id

        sql = f"""
        SELECT {", ".join(_COLUMNS)}
        FROM events
        WHERE {" AND ".join(conditions)}
        ORDER BY timestamp DESC, event_id DESC
        LIMIT {limit + 1}
        """
        result = await self.ch.query(sql, parameters=params)
        rows = result.result_rows
        items = [dict(zip(result.column_names, row)) for row in rows[:limit]]
        next_before: tuple[datetime, str] | None = None
        if len(rows) > limit and items:
            last = items[-1]
            next_before = (last["timestamp"], last["event_id"])
        return {"items": items, "next_before": next_before}
