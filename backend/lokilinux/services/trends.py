"""
LokiLinux — shared trend query for vulnerability findings by day.

Extracted from cves.py's /trend endpoint so /dashboard/trends can reuse the
exact same "open findings per day, derived retroactively from
discovered_at/remediation_date" logic without duplicating the SQL.

Severity is read from cves.cvss_v3_severity, not the denormalized
agent_vulnerabilities.severity column — the latter is set once at scan time
from the distro advisory and never updated when the NVD enrichment worker
(cve_enrichment.py) later corrects a CVE's severity, so it silently drifts
stale. cves.cvss_v3_severity is the one column enrichment keeps current.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TREND_RANGES: dict[str, tuple[int, str]] = {
    "7d": (7, "1 day"),
    "30d": (30, "1 day"),
    "90d": (90, "1 day"),
    "1y": (365, "7 days"),
}

# The one "is this finding still open" definition — every endpoint that
# counts current exposure (not history) filters on this, so they can never
# drift apart the way /dashboard/summary once did with a separate
# is_remediated boolean.
OPEN_VULN_STATUSES = ("OPEN", "PATCH_AVAILABLE", "IN_PROGRESS", "MITIGATED")


async def vulnerability_counts_by_day(db: AsyncSession, range: str) -> list[dict]:
    days, bucket = TREND_RANGES[range]
    rows = (
        await db.execute(
            text(
                """
                SELECT d::date AS day,
                       count(*) FILTER (WHERE c.cvss_v3_severity = 'CRITICAL') AS critical,
                       count(*) FILTER (WHERE c.cvss_v3_severity = 'HIGH') AS high,
                       count(*) FILTER (WHERE c.cvss_v3_severity = 'MEDIUM') AS medium,
                       count(*) FILTER (WHERE c.cvss_v3_severity = 'LOW') AS low
                FROM generate_series(
                    now() - (:days || ' days')::interval, now(), (:bucket)::interval
                ) d
                LEFT JOIN agent_vulnerabilities av
                  ON av.discovered_at <= d
                 AND (av.remediation_date IS NULL OR av.remediation_date > d)
                LEFT JOIN cves c ON c.cve_id = av.cve_id
                GROUP BY d
                ORDER BY d
                """
            ),
            {"days": days, "bucket": bucket},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
