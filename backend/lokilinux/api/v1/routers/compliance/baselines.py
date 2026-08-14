"""
LokiLinux — Compliance: Baseline Manager router.

CRUD for baselines + version workflow (submit/approve/publish/rollback) +
effective-baseline lookup. Mirrors the conventions in routers/policies.py:
CursorPage list responses, get_current_user for reads, require_role for
mutations. AUDITOR gets read access everywhere (matches admin.py's audit-log
precedent) since compliance state is exactly what an auditor role exists to see.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_db, get_nats
from lokilinux.models.baseline import Baseline, BaselineEffective, BaselineVersion
from lokilinux.schemas.baseline import (
    BaselineApprovalCreate,
    BaselineCreate,
    BaselineResponse,
    BaselineVersionCreate,
    BaselineVersionResponse,
    EffectiveBaselineResponse,
)
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.services.baseline_service import BaselineService

router = APIRouter()


# ── Baselines: list / create / detail ─────────────────────────────────────────

@router.get("/baselines", response_model=CursorPage[BaselineResponse])
async def list_baselines(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    scope_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[BaselineResponse]:
    q = select(Baseline).order_by(Baseline.created_at.desc(), Baseline.id.desc())
    if scope_type:
        q = q.where(Baseline.scope_type == scope_type)

    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        ts = datetime.fromisoformat(ts_str)
        q = q.where((Baseline.created_at < ts) | ((Baseline.created_at == ts) & (Baseline.id < UUID(uid))))

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")

    # total count (no cursor filter — lightweight approximate, mirrors servers.py)
    count_q = select(func.count()).select_from(Baseline)
    if scope_type:
        count_q = count_q.where(Baseline.scope_type == scope_type)
    total = (await db.execute(count_q)).scalar()

    return CursorPage[BaselineResponse](
        items=[BaselineResponse.model_validate(b) for b in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("/baselines", response_model=BaselineResponse, status_code=201)
async def create_baseline(
    body: BaselineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> BaselineResponse:
    baseline = await BaselineService(db).create_baseline(
        name=body.name,
        description=body.description,
        scope_type=body.scope_type.value,
        scope_selector=body.scope_selector,
        parent_baseline_id=body.parent_baseline_id,
        expected_state=body.expected_state,
        created_by=safe_user_uuid(current_user),
    )
    return BaselineResponse.model_validate(baseline)


@router.get("/baselines/{baseline_id}", response_model=BaselineResponse)
async def get_baseline(
    baseline_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> BaselineResponse:
    row = (await db.execute(select(Baseline).where(Baseline.id == baseline_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return BaselineResponse.model_validate(row)


# ── Versions ───────────────────────────────────────────────────────────────────

@router.get("/baselines/{baseline_id}/versions", response_model=list[BaselineVersionResponse])
async def list_baseline_versions(
    baseline_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[BaselineVersionResponse]:
    rows = (
        await db.execute(
            select(BaselineVersion)
            .where(BaselineVersion.baseline_id == baseline_id)
            .order_by(BaselineVersion.version.desc())
        )
    ).scalars().all()
    return [BaselineVersionResponse.model_validate(v) for v in rows]


@router.post("/baselines/{baseline_id}/versions", response_model=BaselineVersionResponse, status_code=201)
async def create_baseline_version(
    baseline_id: UUID,
    body: BaselineVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> BaselineVersionResponse:
    version = await BaselineService(db).create_version(
        baseline_id=baseline_id,
        expected_state=body.expected_state,
        change_summary=body.change_summary,
        created_by=safe_user_uuid(current_user),
    )
    return BaselineVersionResponse.model_validate(version)


@router.post("/baselines/{baseline_id}/versions/{version_id}/submit", response_model=BaselineVersionResponse)
async def submit_baseline_version(
    baseline_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> BaselineVersionResponse:
    version = await BaselineService(db).submit(version_id, current_user)
    return BaselineVersionResponse.model_validate(version)


@router.post("/baselines/{baseline_id}/versions/{version_id}/approve", response_model=BaselineVersionResponse)
async def approve_baseline_version(
    baseline_id: UUID,
    version_id: UUID,
    _body: BaselineApprovalCreate | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN")),
) -> BaselineVersionResponse:
    version = await BaselineService(db).approve(version_id, current_user)
    return BaselineVersionResponse.model_validate(version)


@router.post("/baselines/{baseline_id}/versions/{version_id}/publish", response_model=BaselineVersionResponse)
async def publish_baseline_version(
    baseline_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN")),
) -> BaselineVersionResponse:
    version = await BaselineService(db, nats).publish(version_id, current_user)
    return BaselineVersionResponse.model_validate(version)


@router.post("/baselines/{baseline_id}/versions/{version_id}/rollback", response_model=BaselineVersionResponse)
async def rollback_baseline_version(
    baseline_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN")),
) -> BaselineVersionResponse:
    version = await BaselineService(db, nats).rollback(version_id, current_user)
    return BaselineVersionResponse.model_validate(version)


# ── Effective baseline ────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/effective-baseline", response_model=EffectiveBaselineResponse)
async def get_effective_baseline(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> EffectiveBaselineResponse:
    row = (
        await db.execute(select(BaselineEffective).where(BaselineEffective.agent_id == agent_id))
    ).scalar_one_or_none()
    if row is None:
        # baseline_effective is computed by lokilinux-compliance on every
        # COMPLIANCE_BASELINE_PUBLISHED event (fleet-wide recompute,
        # services/compliance/internal/baseline) — a missing row means no
        # baseline has been published since this agent registered, not an
        # engine failure.
        raise HTTPException(status_code=404, detail="Effective baseline not yet computed for this agent")
    return EffectiveBaselineResponse.model_validate(row)
