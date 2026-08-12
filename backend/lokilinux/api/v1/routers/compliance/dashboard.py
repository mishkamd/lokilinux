"""
LokiLinux — Compliance: Dashboard widgets router.

Read-only fleet-wide aggregates for the compliance landing page
(docs/compliance/05-API.md §4): most-failed rules and highest-churn files.
Both query TimescaleDB hypertables (rule_evaluations, drift_events,
file_changes) behind a bounded 7-day window so the dashboard stays cheap
even at fleet scale — never a full-table scan.

Aggregations use plain SQL (text()) rather than ORM constructs: the
GROUP BY + count shape is exactly what they are and mix ORM/text poorly;
drift events, the one ORM-shaped read, use the model.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.models.drift import DriftEvent
from lokilinux.schemas.drift import DriftEventResponse

router = APIRouter()

_DASHBOARD_WINDOW = "interval '7 days'"


class TopViolatingRule(BaseModel):
    rule_id: UUID
    rule_key: str
    title: str
    domain: str
    severity: str
    fail_count: int


class TopViolationsResponse(BaseModel):
    """Both halves of the "Top violations" widget: the most-failed rules
    fleet-wide (docs/compliance/05-API.md §4) and the most recent
    HIGH/CRITICAL drift events — surfaced together so an operator sees the
    rule-level picture and the current incident list on one screen."""

    top_rules: list[TopViolatingRule]
    recent_drift: list[DriftEventResponse]


class TopChangedFile(BaseModel):
    path: str
    change_count: int


@router.get("/dashboard/top-violations", response_model=TopViolationsResponse)
async def top_violations(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> TopViolationsResponse:
    # Most-failed rules: FAIL verdicts in the window, grouped by rule — a
    # rule failing on 40 agents outranks one failing twice on a single
    # agent. The time predicate keeps this on recent hypertable chunks.
    rules_rows = (
        await db.execute(
            text(
                """
                SELECT cr.id, cr.rule_key, cr.title, cr.domain, cr.severity,
                       count(*) AS fail_count
                FROM rule_evaluations re
                JOIN compliance_rules cr ON cr.id = re.rule_id
                WHERE re.result = 'FAIL' AND re.time > now() - """ + _DASHBOARD_WINDOW + """
                GROUP BY cr.id, cr.rule_key, cr.title, cr.domain, cr.severity
                ORDER BY fail_count DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    top_rules = [
        TopViolatingRule(
            rule_id=r["id"],
            rule_key=r["rule_key"],
            title=r["title"],
            domain=r["domain"],
            severity=r["severity"],
            fail_count=r["fail_count"],
        )
        for r in rules_rows
    ]

    # Recent drift, worst severity first (CRITICAL > HIGH > MEDIUM > LOW),
    # then newest — the "what's on fire right now" half of the widget.
    drift_rows = (
        await db.execute(
            select(DriftEvent)
            .where(text(f"time > now() - {_DASHBOARD_WINDOW}"))
            .order_by(
                text("CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END"),
                DriftEvent.time.desc(),
            )
            .limit(limit)
        )
    ).scalars().all()
    recent_drift = [DriftEventResponse.model_validate(d) for d in drift_rows]

    return TopViolationsResponse(top_rules=top_rules, recent_drift=recent_drift)


@router.get("/dashboard/top-changed-files", response_model=list[TopChangedFile])
async def top_changed_files(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[TopChangedFile]:
    """Highest file_changes frequency fleet-wide (docs/compliance/05-API.md
    §4) — the "which files keep changing" signal that points at automation
    fighting a config file or an agent rewriting a path every cycle."""
    rows = (
        await db.execute(
            text(
                """
                SELECT path, count(*) AS change_count
                FROM file_changes
                WHERE time > now() - """ + _DASHBOARD_WINDOW + """
                GROUP BY path
                ORDER BY change_count DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [
        TopChangedFile(path=r["path"], change_count=r["change_count"]) for r in rows
    ]
