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

from datetime import datetime, timedelta, timezone
from typing import Any
import asyncio
import json
import time

import structlog

from lokilinux.ch import ClickHouseStore
from lokilinux.events.schemas import NormalizedEvent
from lokilinux.metrics import clickhouse_insert_errors_total, event_buffer_depth, events_dropped_total
from lokilinux.utils import liveness

logger = structlog.get_logger()

EVENT_INSERT_BATCH = 1000
EVENT_INSERT_FLUSH_SEC = 1.0
EVENT_BUFFER_MAX = 10_000
# After a failed insert, add() stops triggering flushes for this long — otherwise every
# incoming event re-sends the whole failing buffer to a ClickHouse that is already struggling.
EVENT_FLUSH_BACKOFF_SEC = 5.0
# Look-back windows tried in order by query(); None = no lower bound.
_LIST_WINDOWS = (timedelta(days=1), timedelta(days=7), None)

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
        self._retry_after = 0.0
        self._lock = asyncio.Lock()

    async def add(self, event: NormalizedEvent) -> None:
        async with self._lock:
            self._buffer.append(_row(event))
            if self._oldest_buffered_at is None:
                self._oldest_buffered_at = time.monotonic()
            # Cap here too: a slow (not failing) ClickHouse never reaches the requeue path.
            self._enforce_cap()
            should_flush = time.monotonic() >= self._retry_after and (
                len(self._buffer) >= EVENT_INSERT_BATCH
                or (time.monotonic() - self._oldest_buffered_at) > EVENT_INSERT_FLUSH_SEC
            )
            event_buffer_depth.labels(buffer="events").set(len(self._buffer))
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
            event_buffer_depth.labels(buffer="events").set(0)
        try:
            await self.ch.insert("events", batch, column_names=_COLUMNS)
            self._retry_after = 0.0
            liveness.beat("events_flush")
        except Exception:
            logger.error("events.flush_failed", batch_size=len(batch), exc_info=True)
            clickhouse_insert_errors_total.labels(table="events").inc()
            self._retry_after = time.monotonic() + EVENT_FLUSH_BACKOFF_SEC
            await self._requeue_with_backpressure(batch)

    async def _requeue_with_backpressure(self, failed_batch: list[list[Any]]) -> None:
        async with self._lock:
            self._buffer = failed_batch + self._buffer
            if self._oldest_buffered_at is None:
                self._oldest_buffered_at = time.monotonic()
            self._enforce_cap()

    def _enforce_cap(self) -> None:
        """Shed rows above EVENT_BUFFER_MAX. The caller holds self._lock."""
        overflow = len(self._buffer) - EVENT_BUFFER_MAX
        if overflow <= 0:
            return
        # Oldest DEBUG/INFO first, then WARNING — ERROR/CRITICAL are spared by severity.
        droppable = sorted(
            (i for i, row in enumerate(self._buffer) if row[_SEVERITY_COL] not in _NEVER_DROP),
            key=lambda i: (_DROP_PRIORITY.get(self._buffer[i][_SEVERITY_COL], 99), i),
        )
        to_drop = set(droppable[:overflow])
        kept = [row for i, row in enumerate(self._buffer) if i not in to_drop]
        # shortcut: past 2x the cap even ERROR/CRITICAL go (oldest first), so a long outage
        # can't grow the buffer without bound; spill to disk if those losses ever matter.
        excess = len(kept) - EVENT_BUFFER_MAX * 2
        if excess > 0:
            kept = kept[excess:]
        dropped = len(self._buffer) - len(kept)
        if dropped:
            self._buffer = kept
            events_dropped_total.labels(reason="buffer_overflow").inc(dropped)
            event_buffer_depth.labels(buffer="events").set(len(self._buffer))
            logger.warning("events.buffer_overflow_dropped", dropped=dropped)

    async def query(
        self,
        tenant_id: str,
        *,
        type: str | None = None,
        source: str | None = None,
        host_id: str | None = None,
        search: str | None = None,
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
        if search:
            # Substring match on the event type — the UI presents this as a
            # search box, and an exact-match filter silently returns nothing
            # when the operator types a prefix.
            conditions.append("positionCaseInsensitive(type, %(search)s) > 0")
            params["search"] = search
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

        # The sorting key is (tenant, type, timestamp) but the list is ordered by time, so an
        # unbounded query sorts every partition. Read the newest day first and only widen the
        # window while the page isn't full; the partition key (toDate(timestamp)) prunes the rest.
        # shortcut: an almost-empty tenant pays up to 3 cheap queries per page; if the list
        # ever needs deep paging at volume, add a projection ordered by (tenant, timestamp).
        upper = before[0] if before else datetime.now(timezone.utc)
        windows = _LIST_WINDOWS if since is None else (None,)
        for window in windows:
            win_conditions, win_params = list(conditions), dict(params)
            if window is not None:
                win_conditions.append("timestamp >= %(window_start)s")
                win_params["window_start"] = upper - window
            sql = f"""
        SELECT {", ".join(_COLUMNS)}
        FROM events
        WHERE {" AND ".join(win_conditions)}
        ORDER BY timestamp DESC, event_id DESC
        LIMIT {limit + 1}
        """
            result = await self.ch.query(sql, parameters=win_params)
            rows = result.result_rows
            if len(rows) > limit:
                break
        items = [dict(zip(result.column_names, row)) for row in rows[:limit]]
        next_before: tuple[datetime, str] | None = None
        if len(rows) > limit and items:
            last = items[-1]
            next_before = (last["timestamp"], last["event_id"])
        return {"items": items, "next_before": next_before}
