"""
LokiLinux — Workflows router.

CRUD + versioning + publish for the Workflow Engine (Phase 1). Execution
endpoints (run/dry-run/cancel/approve) land in Phase 6 — see plan §11/§17.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.models.workflow import Workflow, WorkflowRun, WorkflowStepRun, WorkflowVersion
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.workflow import (
    DryRunResponse,
    WorkflowCreate,
    WorkflowDetailResponse,
    WorkflowDocument,
    WorkflowResponse,
    WorkflowRunDetailResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowStepRunResponse,
    WorkflowUpdate,
    WorkflowValidateRequest,
    WorkflowVersionCreate,
    WorkflowVersionResponse,
)
from lokilinux.services.workflow_engine import approve_step, cancel_run, dry_run, reject_step, start_run
from lokilinux.services.workflow_service import WorkflowService

router = APIRouter()


# ── Schema (for frontend autocomplete/validation, plan §5) ──────────────────

@router.get("/schema")
async def get_workflow_schema(_: dict = Depends(get_current_user)) -> dict:
    return WorkflowDocument.model_json_schema()


# ── Validate without persisting ──────────────────────────────────────────────

@router.post("/validate")
async def validate_workflow(
    body: WorkflowValidateRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> dict:
    result = await WorkflowService(db).validate(body.yaml)
    return result.model_dump()


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=CursorPage[WorkflowResponse])
async def list_workflows(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[WorkflowResponse]:
    q = select(Workflow).order_by(Workflow.priority.asc(), Workflow.created_at.desc())

    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (Workflow.created_at < ts)
            | ((Workflow.created_at == ts) & (Workflow.id < UUID(uid)))
        )

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")

    return CursorPage[WorkflowResponse](
        items=[WorkflowResponse.model_validate(w) for w in items],
        next_cursor=next_cursor,
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowResponse:
    workflow = await WorkflowService(db).create_workflow(
        name=body.name, yaml_source=body.yaml, created_by=safe_user_uuid(current_user),
    )
    return WorkflowResponse.model_validate(workflow)


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> WorkflowDetailResponse:
    row = (await db.execute(select(Workflow).where(Workflow.id == workflow_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    current_version = None
    if row.current_version_id is not None:
        version_row = (await db.execute(
            select(WorkflowVersion).where(WorkflowVersion.id == row.current_version_id)
        )).scalar_one_or_none()
        if version_row is not None:
            current_version = WorkflowVersionResponse.model_validate(version_row)

    return WorkflowDetailResponse(**WorkflowResponse.model_validate(row).model_dump(), current_version=current_version)


# ── Update metadata ───────────────────────────────────────────────────────────

@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID,
    body: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowResponse:
    changes = body.model_dump(exclude_unset=True)
    if "trigger_type" in changes and changes["trigger_type"] is not None:
        changes["trigger_type"] = changes["trigger_type"].value if hasattr(changes["trigger_type"], "value") else changes["trigger_type"]
    workflow = await WorkflowService(db).update_metadata(workflow_id, changes)
    return WorkflowResponse.model_validate(workflow)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    await WorkflowService(db).delete_workflow(workflow_id)


# ── Versions ──────────────────────────────────────────────────────────────────

@router.get("/{workflow_id}/versions", response_model=CursorPage[WorkflowVersionResponse])
async def list_workflow_versions(
    workflow_id: UUID,
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[WorkflowVersionResponse]:
    q = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id).order_by(WorkflowVersion.version.desc())

    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (WorkflowVersion.created_at < ts)
            | ((WorkflowVersion.created_at == ts) & (WorkflowVersion.id < UUID(uid)))
        )

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")

    return CursorPage[WorkflowVersionResponse](
        items=[WorkflowVersionResponse.model_validate(v) for v in items],
        next_cursor=next_cursor,
    )


@router.post("/{workflow_id}/versions", response_model=WorkflowVersionResponse, status_code=201)
async def create_workflow_version(
    workflow_id: UUID,
    body: WorkflowVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowVersionResponse:
    version = await WorkflowService(db).create_version(
        workflow_id, yaml_source=body.yaml, created_by=safe_user_uuid(current_user),
    )
    return WorkflowVersionResponse.model_validate(version)


@router.put("/{workflow_id}/versions/{version_id}", response_model=WorkflowVersionResponse)
async def update_workflow_version(
    workflow_id: UUID,
    version_id: UUID,
    body: WorkflowVersionCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowVersionResponse:
    version = await WorkflowService(db).update_draft(
        workflow_id, version_id, yaml_source=body.yaml, base_content_hash=body.base_content_hash,
    )
    return WorkflowVersionResponse.model_validate(version)


@router.post("/{workflow_id}/versions/{version_id}/publish", response_model=WorkflowVersionResponse)
async def publish_workflow_version(
    workflow_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowVersionResponse:
    version = await WorkflowService(db).publish_version(workflow_id, version_id, actor=safe_user_uuid(current_user))
    return WorkflowVersionResponse.model_validate(version)


# ── Execution (Phase 6) ───────────────────────────────────────────────────────

@router.post("/{workflow_id}/dry-run", response_model=DryRunResponse)
async def dry_run_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> DryRunResponse:
    return await dry_run(db, workflow_id)


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse, status_code=202)
async def run_workflow(
    workflow_id: UUID,
    body: WorkflowRunRequest = WorkflowRunRequest(),
    db: AsyncSession = Depends(get_db),
    cache=Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowRunResponse:
    run = await start_run(
        db, cache, workflow_id, trigger_type="MANUAL",
        triggered_by=safe_user_uuid(current_user), is_dry_run=body.is_dry_run, nats=nats,
    )
    return WorkflowRunResponse.model_validate(run)


@router.get("/{workflow_id}/runs", response_model=CursorPage[WorkflowRunResponse])
async def list_workflow_runs(
    workflow_id: UUID,
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[WorkflowRunResponse]:
    q = select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id).order_by(WorkflowRun.created_at.desc())

    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (WorkflowRun.created_at < ts)
            | ((WorkflowRun.created_at == ts) & (WorkflowRun.id < UUID(uid)))
        )

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")

    return CursorPage[WorkflowRunResponse](
        items=[WorkflowRunResponse.model_validate(r) for r in items],
        next_cursor=next_cursor,
    )


@router.get("/runs/{run_id}", response_model=WorkflowRunDetailResponse)
async def get_workflow_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> WorkflowRunDetailResponse:
    run = (await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    step_runs = (await db.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run_id).order_by(WorkflowStepRun.created_at.asc())
    )).scalars().all()

    return WorkflowRunDetailResponse(
        **WorkflowRunResponse.model_validate(run).model_dump(),
        step_runs=[WorkflowStepRunResponse.model_validate(sr) for sr in step_runs],
    )


@router.post("/runs/{run_id}/cancel", response_model=WorkflowRunResponse)
async def cancel_workflow_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowRunResponse:
    run = await cancel_run(db, run_id, actor=safe_user_uuid(current_user))
    return WorkflowRunResponse.model_validate(run)


@router.post("/runs/{run_id}/steps/{step_id}/approve", response_model=WorkflowRunResponse)
async def approve_workflow_step(
    run_id: UUID,
    step_id: str,
    db: AsyncSession = Depends(get_db),
    cache=Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowRunResponse:
    run = await approve_step(db, cache, run_id, step_id, actor=safe_user_uuid(current_user), nats=nats)
    return WorkflowRunResponse.model_validate(run)


@router.post("/runs/{run_id}/steps/{step_id}/reject", response_model=WorkflowRunResponse)
async def reject_workflow_step(
    run_id: UUID,
    step_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> WorkflowRunResponse:
    run = await reject_step(db, run_id, step_id, actor=safe_user_uuid(current_user))
    return WorkflowRunResponse.model_validate(run)
