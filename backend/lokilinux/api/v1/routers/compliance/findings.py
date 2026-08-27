"""
LokiLinux — Compliance: Findings router (Enterprise Compliance plan U4/KTD1).

Findings are a read-model, not a new table: a query over rule_evaluations
(append-only hypertable) joined to compliance_rules/agents, deduplicated to
the LATEST verdict per (agent_id, rule_id) via Postgres DISTINCT ON —
mirrors services/compliance's LatestEvaluationsForAgent, just across the
whole fleet instead of one agent. `result` defaults to FAIL (the "what's
currently wrong" view); pass result= explicitly to see PASS/UNKNOWN/etc.

Custom (non-paginate_keyset) cursor pagination: paginate_keyset assumes an
ORM entity at a fixed row index to read the keyset columns off; this query
returns a flat DISTINCT ON subquery with no such entity, so the same
decode/where/limit+1/encode shape is done directly against the subquery's
named columns instead.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_permission, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.models.agent import Agent
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.drift import OPEN_DRIFT_STATUSES, DriftEvent
from lokilinux.models.inventory import InventorySnapshot
from lokilinux.models.rule_evaluation import RuleEvaluation
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.compliance_finding import FindingDetailResponse, FindingResponse
from lokilinux.services.audit_service import AuditService

router = APIRouter()

_FINDING_COLS = (
    RuleEvaluation.time,
    RuleEvaluation.agent_id,
    RuleEvaluation.rule_id,
    RuleEvaluation.policy_set_id,
    RuleEvaluation.result,
    RuleEvaluation.exception_id,
    RuleEvaluation.acknowledged_by,
    RuleEvaluation.acknowledged_at,
    ComplianceRule.rule_key,
    ComplianceRule.title,
    ComplianceRule.domain,
    ComplianceRule.severity,
    Agent.hostname,
)


def _finding_id(agent_id, rule_id, time) -> str:
    return encode_cursor(f"{agent_id}:{rule_id}:{time.isoformat()}")


def _decode_finding_id(finding_id: str) -> tuple[UUID, UUID, datetime]:
    try:
        agent_str, rule_str, time_str = decode_cursor(finding_id).split(":", 2)
        return UUID(agent_str), UUID(rule_str), datetime.fromisoformat(time_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed finding id") from exc


def _latest_per_rule_subquery(
    severity: str | None, domain: str | None, rule_id: UUID | None, agent_id: UUID | None
):
    q = (
        select(*_FINDING_COLS)
        .distinct(RuleEvaluation.agent_id, RuleEvaluation.rule_id)
        .join(ComplianceRule, ComplianceRule.id == RuleEvaluation.rule_id)
        .outerjoin(Agent, Agent.id == RuleEvaluation.agent_id)
    )
    if severity:
        q = q.where(ComplianceRule.severity == severity)
    if domain:
        q = q.where(ComplianceRule.domain == domain)
    if rule_id:
        q = q.where(RuleEvaluation.rule_id == rule_id)
    if agent_id:
        q = q.where(RuleEvaluation.agent_id == agent_id)
    q = q.order_by(RuleEvaluation.agent_id, RuleEvaluation.rule_id, RuleEvaluation.time.desc())
    return q.subquery()


def _to_response(row) -> FindingResponse:
    return FindingResponse(
        id=_finding_id(row.agent_id, row.rule_id, row.time),
        time=row.time,
        agent_id=row.agent_id,
        hostname=row.hostname,
        rule_id=row.rule_id,
        rule_key=row.rule_key,
        title=row.title,
        domain=row.domain,
        severity=row.severity,
        result=row.result,
        exception_id=row.exception_id,
        acknowledged_by=row.acknowledged_by,
        acknowledged_at=row.acknowledged_at,
    )


@router.get("/findings", response_model=CursorPage[FindingResponse])
async def list_findings(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    severity: str | None = Query(None),
    domain: str | None = Query(None),
    rule_id: UUID | None = Query(None),
    agent_id: UUID | None = Query(None),
    result: str | None = Query(
        "FAIL", description="Latest-verdict filter; empty string = any result"
    ),
    since: datetime | None = Query(
        None, description="Only findings last evaluated at/after this time"
    ),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[FindingResponse]:
    sub = _latest_per_rule_subquery(severity, domain, rule_id, agent_id)
    outer = select(sub).order_by(sub.c.time.desc(), sub.c.agent_id.desc())
    if result:
        outer = outer.where(sub.c.result == result)
    if since:
        outer = outer.where(sub.c.time >= since)

    if cursor:
        try:
            ts_str, agent_str = decode_cursor(cursor).rsplit(":", 1)
            ts = datetime.fromisoformat(ts_str)
            key = UUID(agent_str)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Malformed cursor") from exc
        outer = outer.where((sub.c.time < ts) | ((sub.c.time == ts) & (sub.c.agent_id < key)))

    rows = (await db.execute(outer.limit(limit + 1))).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.time.isoformat()}:{last.agent_id}")

    # Total over the same (pre-cursor) predicate — count the dedup'd set,
    # not raw rule_evaluations rows.
    count_inner = select(sub)
    if result:
        count_inner = count_inner.where(sub.c.result == result)
    if since:
        count_inner = count_inner.where(sub.c.time >= since)
    total = (await db.execute(select(func.count()).select_from(count_inner.subquery()))).scalar()

    return CursorPage[FindingResponse](
        items=[_to_response(r) for r in items], next_cursor=next_cursor, total=total
    )


@router.get("/findings/{finding_id}", response_model=FindingDetailResponse)
async def get_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> FindingDetailResponse:
    agent_id, rule_id, time = _decode_finding_id(finding_id)

    result = (
        await db.execute(
            select(RuleEvaluation, ComplianceRule, Agent.hostname)
            .join(ComplianceRule, ComplianceRule.id == RuleEvaluation.rule_id)
            .outerjoin(Agent, Agent.id == RuleEvaluation.agent_id)
            .where(
                RuleEvaluation.agent_id == agent_id,
                RuleEvaluation.rule_id == rule_id,
                RuleEvaluation.time == time,
            )
            # A rule can only be assigned once per agent via one active
            # policy_set_id in practice; if more than one row somehow
            # shares this (agent, rule, time), take any — they'd be the
            # same verdict duplicated across policy sets, not a real
            # ambiguity in the finding itself.
            .limit(1)
        )
    ).first()
    if result is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    evaluation, rule, hostname = result

    snapshot = (
        await db.execute(
            select(InventorySnapshot)
            .where(
                InventorySnapshot.agent_id == agent_id,
                InventorySnapshot.domain == rule.domain,
                InventorySnapshot.taken_at <= time,
            )
            .order_by(InventorySnapshot.taken_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    open_drift = (
        await db.execute(
            select(DriftEvent.id)
            .where(
                DriftEvent.agent_id == agent_id,
                DriftEvent.domain == rule.domain,
                DriftEvent.status.in_(OPEN_DRIFT_STATUSES),
            )
            .order_by(DriftEvent.time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return FindingDetailResponse(
        id=_finding_id(agent_id, rule_id, time),
        time=evaluation.time,
        agent_id=evaluation.agent_id,
        hostname=hostname,
        rule_id=evaluation.rule_id,
        rule_key=rule.rule_key,
        title=rule.title,
        domain=rule.domain,
        severity=rule.severity,
        result=evaluation.result,
        exception_id=evaluation.exception_id,
        acknowledged_by=evaluation.acknowledged_by,
        acknowledged_at=evaluation.acknowledged_at,
        policy_set_id=evaluation.policy_set_id,
        actual_value=evaluation.actual_value,
        expected_value=evaluation.expected_value,
        evidence=evaluation.evidence,
        evidence_hash=evaluation.evidence_hash,
        error_message=evaluation.error_message,
        source=evaluation.source,
        snapshot_id=snapshot.id if snapshot else None,
        snapshot_taken_at=snapshot.taken_at if snapshot else None,
        snapshot_content_hash=snapshot.content_hash if snapshot else None,
        open_drift_event_id=open_drift,
    )


@router.post("/findings/{finding_id}/acknowledge", response_model=FindingDetailResponse)
async def acknowledge_finding(
    finding_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("compliance.findings.acknowledge")),
) -> FindingDetailResponse:
    agent_id, rule_id, time = _decode_finding_id(finding_id)

    row = (
        await db.execute(
            select(RuleEvaluation).where(
                RuleEvaluation.agent_id == agent_id,
                RuleEvaluation.rule_id == rule_id,
                RuleEvaluation.time == time,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Finding not found")

    row.acknowledged_by = safe_user_uuid(current_user)
    row.acknowledged_at = datetime.now(row.time.tzinfo)
    await db.commit()

    await AuditService(db).log(
        action="compliance.finding_acknowledged",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="finding",
        resource_id=finding_id,
        changes={"rule_id": str(rule_id), "agent_id": str(agent_id)},
    )
    return await get_finding(finding_id, db, current_user)
