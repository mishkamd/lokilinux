"""
LokiLinux — Compliance Overview (Enterprise Compliance plan U10).

One endpoint answering "how compliant are we?" instantly:
  - fleet weighted score per category + overall (latest compliance_scores
    sample per agent × category, weighted projection from migration 037)
  - open findings by severity (U4 read model)
  - open drift by severity
  - standards coverage (U8) — CEL-executable rule percentage per standard
  - fleet coverage: how many ACTIVE agents have a score at all (UNKNOWN
    honesty — agents that never reported are visible, not invisible)

Redis-cached 60s: every widget is an aggregate over hypertables; a 60s
staleness window is invisible operationally and keeps the landing page
cheap at fleet scale. Cache is per-user-agnostic (aggregates are
fleet-wide, no per-tenant data inside).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import require_role
from lokilinux.cache import RedisCache
from lokilinux.dependencies import get_cache, get_db

router = APIRouter()

_CACHE_KEY = "compliance:overview:v1"
_CACHE_TTL = 60

# Latest sample per (agent, category): DISTINCT ON with time DESC — the
# append-only hypertable keeps history, the overview wants "now".
_SCORES_SQL = text("""
    SELECT DISTINCT ON (agent_id, category)
           agent_id, category, score,
           COALESCE(weighted_score, score) AS weighted_score,
           unknown_count
    FROM compliance_scores
    ORDER BY agent_id, category, time DESC
""")

_FINDINGS_SQL = text("""
    SELECT cvss_severity, count(*) AS n
    FROM (
        SELECT DISTINCT ON (re.agent_id, re.rule_id)
               re.agent_id, re.rule_id, cr.cvss_v3_severity AS cvss_severity
        FROM rule_evaluations re
        JOIN compliance_rules cr ON cr.id = re.rule_id
        WHERE re.result = 'FAIL'
        ORDER BY re.agent_id, re.rule_id, re.evaluated_at DESC
    ) latest
    GROUP BY cvss_severity
""")

_DRIFT_SQL = text("""
    SELECT severity, count(*) AS n
    FROM drift_events
    WHERE status IN ('OPEN', 'ACKNOWLEDGED')
    GROUP BY severity
""")

_STANDARDS_SQL = text("""
    SELECT ps.source_framework || ' ' || COALESCE(ps.source_version, '') AS standard,
           count(*) AS total_rules,
           count(*) FILTER (WHERE cr.check_source = 'CEL') AS executable_rules
    FROM policy_set_rules psr
    JOIN policy_sets ps ON ps.id = psr.policy_set_id
    LEFT JOIN compliance_rules cr ON cr.id = psr.rule_id
    WHERE ps.source_framework IS NOT NULL
    GROUP BY standard
    ORDER BY standard
""")

_AGENTS_SQL = text("""
    SELECT
        count(*) FILTER (WHERE status = 'ACTIVE') AS active_agents,
        count(DISTINCT cs.agent_id) AS scored_agents
    FROM agents a
    LEFT JOIN (SELECT DISTINCT agent_id FROM compliance_scores
               WHERE time > now() - interval '24 hours') cs
      ON cs.agent_id = a.id
    WHERE a.status = 'ACTIVE'
""")


def _score_summary(rows) -> dict:
    """Fleet aggregate per category: mean of each agent's latest sample.
    overall handled like any category (the Go writer already synthesizes
    it); severity split for findings lives in its own query."""
    by_category: dict[str, dict] = {}
    for agent_id, category, score, weighted, unknown in rows:
        entry = by_category.setdefault(
            category,
            {"category": category, "agents_scored": 0, "score_sum": 0.0,
             "weighted_sum": 0.0, "unknown_total": 0},
        )
        entry["agents_scored"] += 1
        entry["score_sum"] += float(score)
        # NULL weighted (never computed — pre-037 sample) degrades to the
        # legacy score rather than counting as 0 and dragging the mean down.
        entry["weighted_sum"] += float(weighted if weighted is not None else score)
        entry["unknown_total"] += int(unknown or 0)

    out = []
    for entry in by_category.values():
        n = entry["agents_scored"]
        out.append({
            "category": entry["category"],
            "agents_scored": n,
            "score": round(entry["score_sum"] / n, 2) if n else 0.0,
            "weighted_score": round(entry["weighted_sum"] / n, 2) if n else 0.0,
            "unknown_total": entry["unknown_total"],
        })
    out.sort(key=lambda e: (e["category"] != "overall", e["category"]))
    return out


def _severity_counts(rows) -> dict:
    return {r[0] or "UNKNOWN": int(r[1]) for r in rows}


@router.get("/overview")
async def compliance_overview(
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    user: dict = Depends(require_role("OPERATOR", "AUDITOR")),
) -> dict:
    cached = await cache.get_cached(_CACHE_KEY)
    if cached:
        return {**cached, "cached": True}

    scores = _score_summary((await db.execute(_SCORES_SQL)).all())
    findings = _severity_counts((await db.execute(_FINDINGS_SQL)).all())
    drift = _severity_counts((await db.execute(_DRIFT_SQL)).all())
    standards = [
        {
            "standard": r[0].strip(),
            "total_rules": int(r[1]),
            "executable_rules": int(r[2]),
            "coverage_pct": round(100.0 * int(r[2]) / int(r[1]), 1) if int(r[1]) else 0.0,
        }
        for r in (await db.execute(_STANDARDS_SQL)).all()
    ]
    fleet = (await db.execute(_AGENTS_SQL)).one()
    overall = next((s for s in scores if s["category"] == "overall"), None)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "categories": [s for s in scores if s["category"] != "overall"],
        "findings_by_severity": findings,
        "open_findings_total": sum(findings.values()),
        "drift_by_severity": drift,
        "open_drift_total": sum(drift.values()),
        "standards": standards,
        "fleet": {
            "active_agents": int(fleet.active_agents or 0),
            "scored_agents_24h": int(fleet.scored_agents or 0),
            # honesty metric: agents with NO fresh score are UNKNOWN, not
            # compliant — R5's "no partial-credit illusion" at fleet level.
            "unscored_agents": int(fleet.active_agents or 0) - int(fleet.scored_agents or 0),
        },
        "cached": False,
    }
    await cache.set_cached(_CACHE_KEY, payload, ttl=_CACHE_TTL)
    return payload
