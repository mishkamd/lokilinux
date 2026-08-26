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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.models.agent import Agent
from lokilinux.models.drift import OPEN_DRIFT_STATUSES as _OPEN_DRIFT_STATUSES
from lokilinux.models.drift import DriftEvent
from lokilinux.schemas.drift import DriftEventResponse

router = APIRouter()

_DASHBOARD_WINDOW = "interval '7 days'"

_TREND_RANGES = {"7d": "7 days", "30d": "30 days", "90d": "90 days", "1y": "365 days"}


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
            select(DriftEvent, Agent.hostname)
            .outerjoin(Agent, Agent.id == DriftEvent.agent_id)
            .where(text(f"time > now() - {_DASHBOARD_WINDOW}"))
            .order_by(
                text("CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END"),
                DriftEvent.time.desc(),
            )
            .limit(limit)
        )
    ).all()
    recent_drift = [
        DriftEventResponse.model_validate(d).model_copy(update={"hostname": hostname})
        for d, hostname in drift_rows
    ]

    return TopViolationsResponse(top_rules=top_rules, recent_drift=recent_drift)


class ComplianceOverview(BaseModel):
    """The real-data Overview page cards (docs/compliance §22) — every
    number here comes from a live query, never a client-side computation
    over one page of results (the gap this closes: index.vue previously
    counted "Enabled" baselines only from whatever page was loaded)."""

    overall_compliance_pct: float
    critical_violations: int
    high_violations: int
    open_drift: int
    active_baselines: int
    enabled_policies: int
    servers_evaluated: int
    servers_non_compliant: int
    exceptions_active: int
    remediation_pct: float
    resolved_controls: int


@router.get("/overview", response_model=ComplianceOverview)
async def overview(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> ComplianceOverview:
    # Latest verdict per (agent, rule) within the window — same bounded-scan
    # convention as top_violations/top_changed_files above, never a full
    # hypertable scan (docs/compliance §38).
    latest_cte = f"""
        latest AS (
            SELECT DISTINCT ON (re.agent_id, re.rule_id)
                   re.agent_id, re.rule_id, re.result, cr.severity
            FROM rule_evaluations re
            JOIN compliance_rules cr ON cr.id = re.rule_id
            WHERE re.time > now() - {_DASHBOARD_WINDOW}
            ORDER BY re.agent_id, re.rule_id, re.time DESC
        )
    """
    counts_row = (
        await db.execute(
            text(
                f"""
                WITH {latest_cte}
                SELECT
                    count(*) FILTER (WHERE result = 'PASS') AS passed,
                    count(*) FILTER (WHERE result = 'FAIL') AS failed,
                    count(*) FILTER (WHERE result = 'FAIL' AND severity = 'CRITICAL') AS critical,
                    count(*) FILTER (WHERE result = 'FAIL' AND severity = 'HIGH') AS high,
                    count(DISTINCT agent_id) AS servers_evaluated,
                    count(DISTINCT agent_id) FILTER (WHERE result = 'FAIL') AS servers_non_compliant
                FROM latest
                """
            )
        )
    ).mappings().one()

    passed = counts_row["passed"] or 0
    failed = counts_row["failed"] or 0
    applicable = passed + failed
    compliance_pct = round(100.0 * passed / applicable, 2) if applicable > 0 else 0.0

    open_drift = (
        await db.execute(
            select(func.count()).select_from(DriftEvent).where(DriftEvent.status.in_(_OPEN_DRIFT_STATUSES))
        )
    ).scalar() or 0

    active_baselines = (
        await db.execute(text("SELECT count(*) FROM baselines WHERE is_enabled = true"))
    ).scalar() or 0
    enabled_policies = (
        await db.execute(
            text("SELECT count(*) FROM policy_sets WHERE is_enabled = true AND status = 'PUBLISHED'")
        )
    ).scalar() or 0
    exceptions_active = (
        await db.execute(text("SELECT count(*) FROM compliance_exceptions WHERE status = 'ACTIVE'"))
    ).scalar() or 0

    # Remediation progress: of the rules currently failing, how many already
    # have a completed remediation action tracking them — reuses the same
    # `latest` CTE rather than a second full evaluation scan.
    remediation_row = (
        await db.execute(
            text(
                f"""
                WITH {latest_cte},
                failing_rules AS (
                    SELECT DISTINCT rule_id FROM latest WHERE result = 'FAIL'
                ),
                remediated_rules AS (
                    SELECT DISTINCT ra.rule_id
                    FROM remediation_actions ra
                    JOIN remediation_plans rp ON rp.id = ra.remediation_plan_id
                    WHERE rp.status = 'COMPLETED'
                      AND ra.rule_id IN (SELECT rule_id FROM failing_rules)
                )
                SELECT
                    (SELECT count(*) FROM failing_rules) AS failing_total,
                    (SELECT count(*) FROM remediated_rules) AS resolved_controls
                """
            )
        )
    ).mappings().one()

    failing_total = remediation_row["failing_total"] or 0
    resolved_controls = remediation_row["resolved_controls"] or 0
    remediation_pct = (
        round(100.0 * resolved_controls / failing_total, 2) if failing_total > 0 else 100.0
    )

    return ComplianceOverview(
        overall_compliance_pct=compliance_pct,
        critical_violations=counts_row["critical"] or 0,
        high_violations=counts_row["high"] or 0,
        open_drift=open_drift,
        active_baselines=active_baselines,
        enabled_policies=enabled_policies,
        servers_evaluated=counts_row["servers_evaluated"] or 0,
        servers_non_compliant=counts_row["servers_non_compliant"] or 0,
        exceptions_active=exceptions_active,
        remediation_pct=remediation_pct,
        resolved_controls=resolved_controls,
    )


class TrendPoint(BaseModel):
    day: str
    compliance_pct: float


@router.get("/trend", response_model=list[TrendPoint])
async def trend(
    range: str = Query("30d", pattern="^(7d|30d|90d|1y)$"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[TrendPoint]:
    """Fleet-wide daily compliance score (docs/compliance §23), from the
    compliance_scores_daily continuous aggregate (migration 016) — nothing
    queried it before this. avg(avg_score) fleet-wide per day, "overall"
    category only (per-agent trend is a future drill-down, not this widget)."""
    interval = _TREND_RANGES.get(range)
    if interval is None:
        raise HTTPException(status_code=400, detail=f"Unsupported range: {range}")

    rows = (
        await db.execute(
            text(
                f"""
                SELECT day, avg(avg_score) AS compliance_pct
                FROM compliance_scores_daily
                WHERE category = 'overall' AND day > now() - interval '{interval}'
                GROUP BY day
                ORDER BY day
                """
            )
        )
    ).mappings().all()
    return [
        TrendPoint(day=r["day"].date().isoformat(), compliance_pct=round(float(r["compliance_pct"]), 2))
        for r in rows
    ]


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
