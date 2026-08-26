"""
LokiLinux — incident_evidence writes (ClickHouse).

Unlike events/signal occurrences, evidence writes happen once per incident
open (a handful of rows, one per contributing signal) — nowhere near the
volume Task A3/B2's batched repositories exist to absorb, so this is a
direct insert, no buffer.
"""

from datetime import datetime, timezone
from typing import Any

from lokilinux.ch import ClickHouseStore

_COLUMNS = ["timestamp", "tenant", "incident_id", "kind", "ref", "summary"]


async def add_evidence(
    ch: ClickHouseStore, tenant_id: str, incident_id: str, kind: str, ref: str, summary: str
) -> None:
    row = [[datetime.now(timezone.utc), tenant_id, incident_id, kind, ref, summary]]
    await ch.insert("incident_evidence", row, column_names=_COLUMNS)


async def query_evidence(ch: ClickHouseStore, tenant_id: str, incident_id: str) -> list[dict[str, Any]]:
    result = await ch.query(
        f"SELECT {', '.join(_COLUMNS)} FROM incident_evidence "
        "WHERE tenant = %(tenant)s AND incident_id = %(incident_id)s ORDER BY timestamp ASC",
        parameters={"tenant": tenant_id, "incident_id": incident_id},
    )
    return [dict(zip(result.column_names, row)) for row in result.result_rows]
