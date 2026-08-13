"""
LokiLinux — Compliance: Async fleet assessment router (docs/compliance §24).

Creating an assessment only inserts a PENDING compliance_assessments row —
nothing here evaluates anything synchronously. The Go service's leader-only
AssessmentPoller (services/compliance/internal/scheduler) claims and runs it
in the background, reusing the same evidence/exception/platform-filter
evaluation core snapshot ingest uses (services/compliance/internal/ingest/
assessment.go). This endpoint returning 202 with servers_total=0 is correct
— the real counts land once the poller resolves scope_selector against the
fleet.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.models.compliance_assessment import ComplianceAssessment
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.compliance_assessment import AssessmentCreate, AssessmentResponse

router = APIRouter()


@router.post("/assessments", response_model=AssessmentResponse, status_code=202)
async def create_assessment(
    body: AssessmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> AssessmentResponse:
    assessment = ComplianceAssessment(
        scope_selector=body.scope_selector or {},
        policy_set_id=body.policy_set_id,
        status="PENDING",
        created_by=safe_user_uuid(current_user),
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    return AssessmentResponse.model_validate(assessment)


@router.get("/assessments", response_model=CursorPage[AssessmentResponse])
async def list_assessments(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[AssessmentResponse]:
    q = select(ComplianceAssessment).order_by(ComplianceAssessment.created_at.desc(), ComplianceAssessment.id.desc())
    if status:
        q = q.where(ComplianceAssessment.status == status)

    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, aid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (ComplianceAssessment.created_at < ts)
            | ((ComplianceAssessment.created_at == ts) & (ComplianceAssessment.id < UUID(aid)))
        )
    q = q.limit(limit + 1)

    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")

    count_q = select(func.count()).select_from(ComplianceAssessment)
    if status:
        count_q = count_q.where(ComplianceAssessment.status == status)
    total = (await db.execute(count_q)).scalar()

    return CursorPage[AssessmentResponse](
        items=[AssessmentResponse.model_validate(a) for a in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/assessments/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment(
    assessment_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> AssessmentResponse:
    row = (
        await db.execute(select(ComplianceAssessment).where(ComplianceAssessment.id == assessment_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return AssessmentResponse.model_validate(row)
