"""
LokiLinux — Compliance: File Integrity Monitoring router.

Read-only. file_hashes/file_changes rows are written by lokilinux-compliance
(services/compliance/internal/ingest/file_integrity.go), never by this API —
same pattern as drift.py and inventory.py.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.models.agent import Agent
from lokilinux.models.drift import OPEN_DRIFT_STATUSES
from lokilinux.models.drift import DriftEvent
from lokilinux.models.file_integrity import FileChange, FileHash
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.drift import DriftEventResponse
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
    q = (
        select(FileChange, Agent.hostname)
        .outerjoin(Agent, Agent.id == FileChange.agent_id)
        .order_by(FileChange.time.desc())
    )
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

    rows = (await db.execute(q)).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1][0]
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
        items=[
            FileChangeResponse.model_validate(c).model_copy(update={"hostname": hostname})
            for c, hostname in items
        ],
        next_cursor=next_cursor,
        total=total,
    )


class RelatedRule(BaseModel):
    rule_id: UUID
    rule_key: str
    title: str
    domain: str


class ServerRef(BaseModel):
    agent_id: UUID
    hostname: str | None = None


class FileChangePathDetail(BaseModel):
    """A "Top Changed Files" card click drills into this (docs/compliance
    §35): every server that has ever reported a change to this exact path,
    its recent timeline (hashes/permissions/owners), and what compliance
    context it feeds — the rules that depend on it (F3's resource index)
    and any still-open drift on those rules' domains."""

    path: str
    servers: list[ServerRef]
    timeline: list[FileChangeResponse]
    related_rules: list[RelatedRule]
    related_drift: list[DriftEventResponse]


@router.get("/file-changes/by-path", response_model=FileChangePathDetail)
async def get_file_changes_by_path(
    path: str = Query(..., description="Exact file path, e.g. /etc/ssh/sshd_config"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> FileChangePathDetail:
    server_rows = (
        await db.execute(
            select(FileChange.agent_id, Agent.hostname)
            .outerjoin(Agent, Agent.id == FileChange.agent_id)
            .where(FileChange.path == path)
            .distinct()
        )
    ).all()
    servers = [aid for aid, _hostname in server_rows]
    server_refs = [ServerRef(agent_id=aid, hostname=hostname) for aid, hostname in server_rows]

    timeline_rows = (
        await db.execute(
            select(FileChange, Agent.hostname)
            .outerjoin(Agent, Agent.id == FileChange.agent_id)
            .where(FileChange.path == path)
            .order_by(FileChange.time.desc())
            .limit(50)
        )
    ).all()

    rule_rows = (
        await db.execute(
            text(
                """
                SELECT cr.id, cr.rule_key, cr.title, cr.domain
                FROM compliance_rule_resources crr
                JOIN compliance_rules cr ON cr.id = crr.rule_id
                WHERE crr.resource_type = 'FILE' AND crr.resource_path = :path
                """
            ),
            {"path": path},
        )
    ).mappings().all()
    related_rules = [
        RelatedRule(rule_id=r["id"], rule_key=r["rule_key"], title=r["title"], domain=r["domain"])
        for r in rule_rows
    ]

    related_drift: list[DriftEventResponse] = []
    domains = {r.domain for r in related_rules}
    if domains and servers:
        drift_rows = (
            await db.execute(
                select(DriftEvent, Agent.hostname)
                .outerjoin(Agent, Agent.id == DriftEvent.agent_id)
                .where(
                    DriftEvent.domain.in_(domains),
                    DriftEvent.agent_id.in_(servers),
                    DriftEvent.status.in_(OPEN_DRIFT_STATUSES),
                )
                .order_by(DriftEvent.time.desc())
                .limit(20)
            )
        ).all()
        related_drift = [
            DriftEventResponse.model_validate(d).model_copy(update={"hostname": hostname})
            for d, hostname in drift_rows
        ]

    return FileChangePathDetail(
        path=path,
        servers=server_refs,
        timeline=[
            FileChangeResponse.model_validate(c).model_copy(update={"hostname": hostname})
            for c, hostname in timeline_rows
        ],
        related_rules=related_rules,
        related_drift=related_drift,
    )
