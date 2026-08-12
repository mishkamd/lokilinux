"""
LokiLinux — Compliance: File Integrity Monitoring router.

Read-only. file_hashes/file_changes rows are written by lokilinux-compliance
(services/compliance/internal/ingest/file_integrity.go), never by this API —
same pattern as drift.py and inventory.py.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.models.file_integrity import FileChange, FileHash
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.file_integrity import FileChangeResponse, FileHashResponse

router = APIRouter()


@router.get("/agents/{agent_id}/file-hashes", response_model=list[FileHashResponse])
async def list_file_hashes(
    agent_id: UUID,
    path_prefix: str | None = Query(None, description="Filter to paths starting with this prefix"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[FileHashResponse]:
    q = select(FileHash).where(FileHash.agent_id == agent_id).order_by(FileHash.path)
    if path_prefix:
        q = q.where(FileHash.path.startswith(path_prefix))
    rows = (await db.execute(q)).scalars().all()
    return [FileHashResponse.model_validate(r) for r in rows]


@router.get("/file-changes", response_model=CursorPage[FileChangeResponse])
async def list_file_changes(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    agent_id: UUID | None = Query(None),
    change_kind: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[FileChangeResponse]:
    q = select(FileChange).order_by(FileChange.time.desc())
    if agent_id:
        q = q.where(FileChange.agent_id == agent_id)
    if change_kind:
        q = q.where(FileChange.change_kind == change_kind)
    if cursor:
        raw = decode_cursor(cursor)
        ts_str, path = raw.rsplit("|", 1)
        ts = datetime.fromisoformat(ts_str)
        q = q.where((FileChange.time < ts) | ((FileChange.time == ts) & (FileChange.path < path)))
    q = q.limit(limit + 1)

    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        # Use | instead of : as separator because POSIX paths may contain ':'
        next_cursor = encode_cursor(f"{last.time.isoformat()}|{last.path}")

    # total count (no cursor filter — lightweight approximate, mirrors servers.py)
    count_q = select(func.count()).select_from(FileChange)
    if agent_id:
        count_q = count_q.where(FileChange.agent_id == agent_id)
    if change_kind:
        count_q = count_q.where(FileChange.change_kind == change_kind)
    total = (await db.execute(count_q)).scalar()

    return CursorPage[FileChangeResponse](
        items=[FileChangeResponse.model_validate(c) for c in items],
        next_cursor=next_cursor,
        total=total,
    )
