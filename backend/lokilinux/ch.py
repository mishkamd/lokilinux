"""
LokiLinux — ClickHouse event store client.

Owns raw event history, signal occurrences, and incident evidence (append-only,
TTL-retained). PostgreSQL never stores these — see
docs/superpowers/plans/2026-08-24-observability-event-intelligence.md §2
(data ownership contract).

clickhouse-connect is a sync client; every call here is wrapped in
asyncio.to_thread so it doesn't block the event loop — there is no maintained
async ClickHouse client for the versions pinned in this project.
"""

from typing import Any
from urllib.parse import urlsplit
import asyncio

import clickhouse_connect
import structlog

from lokilinux.metrics import ch_operation_duration_seconds

logger = structlog.get_logger()


def _events_ddl(retention_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS events (
  timestamp DateTime64(3),
  event_id UUID,
  tenant LowCardinality(String),
  source LowCardinality(String),
  type LowCardinality(String),
  severity LowCardinality(String),
  host_id String,
  service String,
  fingerprint String,
  schema_version UInt8 DEFAULT 1,
  payload String DEFAULT ''
) ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (tenant, type, timestamp)
TTL toDateTime(timestamp) + INTERVAL {int(retention_days)} DAY
""".strip()


def _signal_occurrences_ddl(retention_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS signal_occurrences (
  timestamp DateTime64(3),
  tenant LowCardinality(String),
  signal_type LowCardinality(String),
  severity LowCardinality(String),
  host_id String,
  service String,
  fingerprint String,
  value Float64 DEFAULT 0,
  metadata String DEFAULT ''
) ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (tenant, signal_type, timestamp)
TTL toDateTime(timestamp) + INTERVAL {int(retention_days)} DAY
""".strip()


def _incident_evidence_ddl(retention_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS incident_evidence (
  timestamp DateTime64(3),
  tenant LowCardinality(String),
  incident_id UUID,
  kind LowCardinality(String),
  ref String,
  summary String
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

    async def connect(self) -> None:
        parsed = urlsplit(self.url)
        self._client = await asyncio.to_thread(
            clickhouse_connect.get_client,
            host=parsed.hostname or "localhost",
            port=parsed.port or 8123,
            username=self.user,
            password=self.password,
            database=self.database,
        )
        logger.info("clickhouse.connected", url=self.url, database=self.database)

    async def disconnect(self) -> None:
        if self._client:
            await asyncio.to_thread(self._client.close)

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self._client.command, "SELECT 1")
            return True
        except Exception:
            return False

    async def command(self, sql: str) -> Any:
        return await asyncio.to_thread(self._client.command, sql)

    async def query(self, sql: str, parameters: dict | None = None) -> Any:
        with ch_operation_duration_seconds.labels(operation="query").time():
            return await asyncio.to_thread(self._client.query, sql, parameters=parameters)

    async def insert(self, table: str, data: list[list[Any]], column_names: list[str]) -> None:
        with ch_operation_duration_seconds.labels(operation="insert").time():
            await asyncio.to_thread(self._client.insert, table, data, column_names=column_names)

    async def ensure_tables(
        self,
        *,
        event_retention_days: int,
        signal_occurrence_retention_days: int,
        incident_evidence_retention_days: int,
    ) -> None:
        """Idempotent DDL bootstrap — safe to call on every startup."""
        await self.command(_events_ddl(event_retention_days))
        await self.command(_signal_occurrences_ddl(signal_occurrence_retention_days))
        await self.command(_incident_evidence_ddl(incident_evidence_retention_days))
        logger.info("clickhouse.tables_ready")
