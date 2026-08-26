"""
LokiLinux — shared keyset (cursor) pagination for the compliance routers.

One implementation of the decode-cursor -> keyset WHERE -> limit+1 ->
has_more -> encode-cursor dance that was previously copy-pasted into every
list endpoint (drift, exceptions, baselines, assessments, reports,
remediation, policy_engine, file_integrity). The count query stays
endpoint-local — only this mechanical block was duplicated verbatim.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.schemas.common import decode_cursor, encode_cursor


async def paginate_keyset(
    db: AsyncSession,
    q,
    *,
    # Ordering columns — the query must already ORDER BY ts_col DESC, tie_col DESC.
    ts_col: ColumnElement,
    tie_col: ColumnElement,
    # Request parameters.
    cursor: str | None,
    limit: int,
    # How to read the last row's key when building the next cursor: which
    # tuple index holds the entity and which attribute names carry the key.
    # scalars=True means q returns entities directly, not row tuples.
    entity_index: int = 0,
    ts_attr: str = "created_at",
    tie_attr: str = "id",
    tie_uuid: bool = True,
    sep: str = ":",
    scalars: bool = False,
) -> tuple[list[Any], str | None]:
    """Apply the keyset predicate for `cursor`, execute `q` with limit+1,
    and return (page_items, next_cursor)."""
    if cursor:
        try:
            ts_str, tail = decode_cursor(cursor).rsplit(sep, 1)
            ts = datetime.fromisoformat(ts_str)
            key: Any = UUID(tail) if tie_uuid else tail
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Malformed cursor") from exc
        q = q.where((ts_col < ts) | ((ts_col == ts) & (tie_col < key)))

    result = await db.execute(q.limit(limit + 1))
    rows = result.scalars().all() if scalars else result.all()
    has_more = len(rows) > limit
    items = rows[:limit]

    next_cursor = None
    if has_more and items:
        last = items[-1] if scalars else items[-1][entity_index]
        next_cursor = encode_cursor(
            f"{getattr(last, ts_attr).isoformat()}{sep}{getattr(last, tie_attr)}"
        )
    return items, next_cursor
