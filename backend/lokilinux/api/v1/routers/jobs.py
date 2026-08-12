"""
LokiLinux — Jobs router.

GET    /jobs         — cursor-paginated list, filters: agent_id, status
POST   /jobs         — create job (SHA256 dedup_key)
GET    /jobs/{id}    — detail + result
DELETE /jobs/{id}    — cancel (QUEUED/SCHEDULED only)
"""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.cache import TTL_JOB_STATUS, RedisCache
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.models.agent import Agent
from lokilinux.models.job import Job, JobResult
from lokilinux.models.job import JobStatus as JobStatusModel
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.job import JobCreate, JobResponse, JobResultResponse, JobStatus
from lokilinux.services.job_service import JobService

router = APIRouter()

_CANCELLABLE = {JobStatusModel.QUEUED, JobStatusModel.SCHEDULED}


# ── List jobs ─────────────────────────────────────────────────────────────────

@router.get("", response_model=CursorPage[JobResponse])
async def list_jobs(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    agent_id: str | None = Query(None),
    status: JobStatus | None = Query(None),
    policy_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> CursorPage[JobResponse]:
    cache_key = f"job:list:{agent_id}:{status}:{policy_id}:{cursor}:{limit}"
    if hit := await cache.get_cached(cache_key):
        return CursorPage[JobResponse].model_validate(hit)

    q = select(Job).order_by(Job.created_at.desc(), Job.id.desc())

    if status:
        q = q.where(Job.status == status.value)
    if agent_id:
        # JSONB containment (@>) matches the exact array element, not a substring
        q = q.where(Job.target_servers["agent_ids"].contains([agent_id]))
    if policy_id:
        # Powers a policy's "Executions" tab — jobs.policy_id existed since
        # 001 but nothing ever queried by it until now.
        q = q.where(Job.policy_id == policy_id)

    if cursor:
        raw = decode_cursor(cursor)
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        from datetime import datetime
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (Job.created_at < ts)
            | ((Job.created_at == ts) & (Job.id < UUID(uid)))
        )

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")

    # total count (no cursor filter — lightweight approximate, mirrors servers.py)
    count_q = select(func.count()).select_from(Job)
    if status:
        count_q = count_q.where(Job.status == status.value)
    if agent_id:
        count_q = count_q.where(Job.target_servers["agent_ids"].contains([agent_id]))
    if policy_id:
        count_q = count_q.where(Job.policy_id == policy_id)
    total = (await db.execute(count_q)).scalar()

    page = CursorPage[JobResponse](
        items=[JobResponse.model_validate(j) for j in items],
        next_cursor=next_cursor,
        total=total,
    )
    await cache.set_cached(cache_key, json.loads(page.model_dump_json()), ttl=TTL_JOB_STATUS)
    return page


# ── Create job ────────────────────────────────────────────────────────────────

@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    body: JobCreate,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    service = JobService(db, cache, nats)
    try:
        job = await service.create_job(
            name=body.name,
            job_type=body.job_type.value,
            target_servers=body.target_servers,
            parameters=body.parameters,
            description=body.description,
            scheduled_time=body.scheduled_time,
            policy_id=body.policy_id,
            created_by=safe_user_uuid(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return JobResponse.model_validate(job)


# ── Job detail ────────────────────────────────────────────────────────────────

@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> JobResponse:
    cache_key = f"job:{job_id}:status"
    if hit := await cache.get_cached(cache_key):
        return JobResponse.model_validate(hit)

    row = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    resp = JobResponse.model_validate(row)
    await cache.set_cached(cache_key, json.loads(resp.model_dump_json()), ttl=TTL_JOB_STATUS)
    return resp


# ── Job results (per agent) ──────────────────────────────────────────────────

@router.get("/{job_id}/results", response_model=list[JobResultResponse])
async def get_job_results(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[JobResultResponse]:
    rows = (
        await db.execute(
            select(JobResult, Agent.hostname)
            .join(Agent, Agent.id == JobResult.agent_id)
            .where(JobResult.job_id == job_id)
            .order_by(JobResult.id)
        )
    ).all()

    return [
        JobResultResponse(
            agent_id=jr.agent_id,
            hostname=hostname,
            status=jr.status,
            exit_code=jr.exit_code,
            error_message=jr.error_message,
            stdout=jr.stdout,
            stderr=jr.stderr,
            duration_seconds=jr.duration_seconds,
            started_at=jr.started_at,
            completed_at=jr.completed_at,
        )
        for jr, hostname in rows
    ]


# ── Approve job (requires_approval gate) ─────────────────────────────────────

@router.post("/{job_id}/approve", response_model=JobResponse)
async def approve_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> JobResponse:
    service = JobService(db, cache, nats)
    try:
        job = await service.approve_job(job_id, safe_user_uuid(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobResponse.model_validate(job)


# ── Cancel job ────────────────────────────────────────────────────────────────

@router.delete("/{job_id}", status_code=204)
async def cancel_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> None:
    row = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if row.status not in _CANCELLABLE:
        raise HTTPException(status_code=409, detail="Job cannot be cancelled in current state")

    row.status = JobStatusModel.CANCELLED
    await db.flush()
    if row.job_type == "COMPLIANCE_REMEDIATE":
        from lokilinux.services.job_service import sync_remediation_plan
        await sync_remediation_plan(db, row.id)
    await db.commit()
    await cache.invalidate(f"job:{job_id}:status")
