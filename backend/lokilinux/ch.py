"""
LokiLinux — ClickHouse event store client.

Owns raw event history, signal occurrences, and incident evidence (append-only,
TTL-retained). PostgreSQL never stores these — see
docs/superpowers/plans/2026-08-24-observability-event-intelligence.md §2
(data ownership contract).

clickhouse-connect is a sync client; every call here is wrapped in
asyncio.to_thread so it doesn't block the event loop — there is no maintained
async ClickHouse client for the versions pinned in this project.

Three operational properties this client guarantees (MIS-138/140/141):
- it never blocks forever (connect/read/query timeouts),
- it never shares the default thread pool with the rest of the app,
- it degrades instead of taking the API down: when ClickHouse is unreachable
  the store raises ClickHouseUnavailable and the API keeps serving.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any
from urllib.parse import urlsplit
import asyncio

import clickhouse_connect
import structlog

from lokilinux.metrics import ch_operation_duration_seconds

logger = structlog.get_logger()

# ── Execution budget (MIS-140) ───────────────────────────────────────────────
# A hung ClickHouse must not pin a worker thread forever: the handshake is
# bounded, the response read is bounded, and the server-side query is bounded.
_CONNECT_TIMEOUT_S = 5
_SEND_RECEIVE_TIMEOUT_S = 60
_MAX_EXECUTION_TIME_S = 60

# ── Dedicated thread pool (MIS-141) ──────────────────────────────────────────
# Every CH call blocks a thread while it waits on the socket. Sharing the
# default executor with the rest of the app means a slow CH can starve
# unrelated to_thread callers (boto3, blocking HTTP).
# ponytail: fixed at 4 workers — raise only if a node ever saturates it.
_CH_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ch")


class ClickHouseUnavailable(RuntimeError):
    """ClickHouse is unreachable — the store is degraded, not broken."""


# ── Schema (MIS-142) ─────────────────────────────────────────────────────────
# One source of truth: the CREATE DDL *and* the "add the missing column"
# ALTERs are both derived from these lists, so a new column can never land in
# only one of them. Adding a column to a list is enough — ensure_tables() adds
# it to existing tables too (CREATE TABLE IF NOT EXISTS never alters one).
_EVENTS_COLUMNS: list[tuple[str, str]] = [
    ("timestamp", "DateTime64(3)"),
    ("event_id", "UUID"),
    ("tenant", "LowCardinality(String)"),
    ("source", "LowCardinality(String)"),
    ("type", "LowCardinality(String)"),
    ("severity", "LowCardinality(String)"),
    ("host_id", "String"),
    ("service", "String"),
    ("fingerprint", "String"),
    ("schema_version", "UInt8 DEFAULT 1"),
    ("payload", "String DEFAULT ''"),
]

_SIGNAL_OCCURRENCES_COLUMNS: list[tuple[str, str]] = [
    ("timestamp", "DateTime64(3)"),
    ("tenant", "LowCardinality(String)"),
    ("signal_type", "LowCardinality(String)"),
    ("severity", "LowCardinality(String)"),
    ("host_id", "String"),
    ("service", "String"),
    ("fingerprint", "String"),
    ("value", "Float64 DEFAULT 0"),
    ("metadata", "String DEFAULT ''"),
]

_INCIDENT_EVIDENCE_COLUMNS: list[tuple[str, str]] = [
    ("timestamp", "DateTime64(3)"),
    ("tenant", "LowCardinality(String)"),
    ("incident_id", "UUID"),
    ("kind", "LowCardinality(String)"),
    ("ref", "String"),
    ("summary", "String"),
]


def _columns_sql(columns: list[tuple[str, str]]) -> str:
    return ",\n  ".join(f"{name} {typ}" for name, typ in columns)


def _events_ddl(retention_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS events (
  {_columns_sql(_EVENTS_COLUMNS)}
) ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (tenant, type, timestamp)
TTL toDateTime(timestamp) + INTERVAL {int(retention_days)} DAY
""".strip()


def _signal_occurrences_ddl(retention_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS signal_occurrences (
  {_columns_sql(_SIGNAL_OCCURRENCES_COLUMNS)}
) ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (tenant, signal_type, timestamp)
TTL toDateTime(timestamp) + INTERVAL {int(retention_days)} DAY
""".strip()


def _incident_evidence_ddl(retention_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS incident_evidence (
  {_columns_sql(_INCIDENT_EVIDENCE_COLUMNS)}
) ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (tenant, incident_id, timestamp)
TTL toDateTime(timestamp) + INTERVAL {int(retention_days)} DAY
""".strip()


class ClickHouseStore:
    """Async-wrapped ClickHouse client + idempotent schema bootstrap."""

    def __init__(self, url: str, user: str, password: str, database: str) -> None:
        self.url = url
        self.user = user
        self.password = password
        self.database = database
        self._client: Any = None
        self._connect_lock = asyncio.Lock()

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking ClickHouse call on the dedicated pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_CH_POOL, partial(fn, *args, **kwargs))

    async def connect(self) -> None:
        """Connect, or stay degraded. Never raises (MIS-138)."""
        parsed = urlsplit(self.url)
        try:
            self._client = await self._run(
                clickhouse_connect.get_client,
                host=parsed.hostname or "localhost",
                port=parsed.port or 8123,
                username=self.user,
                password=self.password,
                database=self.database,
                connect_timeout=_CONNECT_TIMEOUT_S,
                send_receive_timeout=_SEND_RECEIVE_TIMEOUT_S,
            )
        except Exception:
            self._client = None
            logger.error("clickhouse.connect_failed", url=self.url, exc_info=True)
            return
        logger.info("clickhouse.connected", url=self.url, database=self.database)

    async def _ensure_connected(self) -> bool:
        """Lazily (re)connect — a CH outage at boot must not leave the API
        permanently degraded: the next call retries the connection."""
        if self._client is not None:
            return True
        async with self._connect_lock:
            if self._client is None:
                await self.connect()
        return self._client is not None

    async def disconnect(self) -> None:
        if self._client:
            await self._run(self._client.close)
            self._client = None

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._run(self._client.command, "SELECT 1")
            return True
        except Exception:
            return False

    async def command(self, sql: str) -> Any:
        if not await self._ensure_connected():
            raise ClickHouseUnavailable(f"clickhouse unreachable: {self.url}")
        return await self._run(self._client.command, sql)

    async def query(self, sql: str, parameters: dict | None = None) -> Any:
        if not await self._ensure_connected():
            raise ClickHouseUnavailable(f"clickhouse unreachable: {self.url}")
        with ch_operation_duration_seconds.labels(operation="query").time():
            return await self._run(
                self._client.query,
                sql,
                parameters=parameters,
                settings={"max_execution_time": _MAX_EXECUTION_TIME_S},
            )

    async def insert(self, table: str, data: list[list[Any]], column_names: list[str]) -> None:
        if not await self._ensure_connected():
            raise ClickHouseUnavailable(f"clickhouse unreachable: {self.url}")
        with ch_operation_duration_seconds.labels(operation="insert").time():
            await self._run(
                self._client.insert,
                table,
                data,
                column_names=column_names,
                settings={"max_execution_time": _MAX_EXECUTION_TIME_S},
            )

    async def ensure_tables(
        self,
        *,
        event_retention_days: int,
        signal_occurrence_retention_days: int,
        incident_evidence_retention_days: int,
    ) -> None:
        """Idempotent DDL bootstrap — safe to call on every startup.

        CREATE IF NOT EXISTS never touches an existing table, so a column added
        to the schema lists would stay missing on tables created by an older
        version. After the CREATE, missing columns are added with ALTER.
        """
        await self.command(_events_ddl(event_retention_days))
        await self.command(_signal_occurrences_ddl(signal_occurrence_retention_days))
        await self.command(_incident_evidence_ddl(incident_evidence_retention_days))
        await self._ensure_columns("events", _EVENTS_COLUMNS)
        await self._ensure_columns("signal_occurrences", _SIGNAL_OCCURRENCES_COLUMNS)
        await self._ensure_columns("incident_evidence", _INCIDENT_EVIDENCE_COLUMNS)
        logger.info("clickhouse.tables_ready")

    async def _ensure_columns(self, table: str, columns: list[tuple[str, str]]) -> None:
        """ADD COLUMN for anything the live table doesn't have yet.

        Type changes are NOT handled — a column that exists with a different
        type is left alone; changing it needs an explicit migration.
        """
        existing = {str(row[0]) for row in await self.query(f"DESCRIBE TABLE {table}")}
        for name, typ in columns:
            if name in existing:
                continue
            await self.command(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
            logger.info("clickhouse.column_added", table=table, column=name)
