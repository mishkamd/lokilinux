"""
LokiLinux — Configuration domain alias router (Enterprise Compliance plan
U2 Task 2). Thin, contract-compatible delegates over the existing
Compliance routers' handlers — Configuration and Compliance become
visibly separate products at the URL/nav level without moving any engine,
table, or business logic (plan U2 Task 4: "no engine moves; no table
renames"). Read-only: mutations (acknowledge/suppress/resolve) stay under
/compliance/* only, matching the plan's "reusing compliance components
where read-only" framing for the Configuration surface.

Delegates to the exact same handler functions the /compliance/* routes
call — a change to filtering/pagination behavior there is automatically
reflected here, so the two surfaces can't silently drift apart.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.schemas.baseline import BaselineListResponse
from lokilinux.schemas.common import CursorPage
from lokilinux.schemas.drift import DriftEventResponse

from .compliance.baselines import list_baselines
from .compliance.drift import list_drift_events

router = APIRouter()


@router.get("/baselines", response_model=BaselineListResponse)
async def configuration_baselines(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    scope_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> BaselineListResponse:
    return await list_baselines(cursor, limit, scope_type, db, current_user)


@router.get("/drift", response_model=CursorPage[DriftEventResponse])
async def configuration_drift(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    severity: str | None = Query(None),
    domain: str | None = Query(None),
    agent_id: UUID | None = Query(None),
    acknowledged: bool | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> CursorPage[DriftEventResponse]:
    return await list_drift_events(
        cursor, limit, severity, domain, agent_id, acknowledged, status, db, current_user
    )
