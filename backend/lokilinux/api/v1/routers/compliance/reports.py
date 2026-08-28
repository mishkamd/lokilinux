"""
LokiLinux — Compliance: Reporting Engine router (docs/compliance/05-API.md §7).
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.models.compliance_report import ComplianceReport
from lokilinux.api.v1.routers.compliance._pagination import paginate_keyset
from lokilinux.schemas.common import CursorPage
from lokilinux.schemas.compliance_report import ComplianceReportCreate, ComplianceReportResponse
from lokilinux.services.report_service import FORMAT_CONTENT_TYPES, generate_report
from lokilinux.settings_schema import get_setting_value

router = APIRouter()


@router.get("/reports/formats")
async def list_report_formats(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> dict[str, bool]:
    """Plan R10: JSON/CSV are always available; XLSX/PDF follow the
    `reports.xlsx_pdf_enabled` settings flag — the UI reads this instead of
    hardcoding the format list, so a disabled office format never shows up
    as a pickable option rather than failing after the fact."""
    xlsx_pdf = bool(await get_setting_value(db, "reports.xlsx_pdf_enabled"))
    return {"JSON": True, "CSV": True, "XLSX": xlsx_pdf, "PDF": xlsx_pdf}


@router.post("/reports", response_model=ComplianceReportResponse, status_code=202)
async def create_report(
    body: ComplianceReportCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> ComplianceReportResponse:
    report = ComplianceReport(
        report_type=body.report_type.value,
        format=body.format.value,
        params=body.params,
        status="PENDING",
        generated_by=safe_user_uuid(current_user),
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    session_factory = request.app.state.session_factory
    background_tasks.add_task(_run_report_generation, session_factory, report.id)

    return ComplianceReportResponse.model_validate(report)


async def _run_report_generation(session_factory, report_id: UUID) -> None:
    async with session_factory() as db:
        report = (
            await db.execute(select(ComplianceReport).where(ComplianceReport.id == report_id))
        ).scalar_one_or_none()
        if report is None:
            return
        await generate_report(db, report)


@router.get("/reports", response_model=CursorPage[ComplianceReportResponse])
async def list_reports(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    status_: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[ComplianceReportResponse]:
    q = select(ComplianceReport).order_by(
        ComplianceReport.created_at.desc(), ComplianceReport.id.desc()
    )
    if status_:
        q = q.where(ComplianceReport.status == status_)

    items, next_cursor = await paginate_keyset(
        db, q,
        ts_col=ComplianceReport.created_at, tie_col=ComplianceReport.id,
        cursor=cursor, limit=limit,
        scalars=True,
    )

    # total count (no cursor filter — lightweight approximate, mirrors servers.py)
    count_q = select(func.count()).select_from(ComplianceReport)
    if status_:
        count_q = count_q.where(ComplianceReport.status == status_)
    total = (await db.execute(count_q)).scalar()

    return CursorPage[ComplianceReportResponse](
        items=[ComplianceReportResponse.model_validate(r) for r in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> Response:
    report = (
        await db.execute(select(ComplianceReport).where(ComplianceReport.id == report_id))
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "COMPLETED" or report.body is None:
        raise HTTPException(
            status_code=409, detail=f"Report is {report.status}, not ready for download"
        )

    ext = report.format.lower()
    return Response(
        content=report.body,
        media_type=FORMAT_CONTENT_TYPES.get(report.format, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="compliance-report-{report_id}.{ext}"'
        },
    )
