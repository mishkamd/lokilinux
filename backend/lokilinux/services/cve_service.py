"""
LokiLinux — CVEService: per-agent vulnerability queries with cache-aside.

AgentVulnerability.cve_id is String(50) FK to cves.cve_id (not cves.id).
AgentVulnerability.severity is the denormalized severity column on the vuln row.
"""

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.cve import CVE


class CVEService:
    def __init__(self, db: AsyncSession, cache: RedisCache) -> None:
        self.db = db
        self.cache = cache

    async def import_nvd_cve(self, cve_data: dict) -> str:
        """Map one NVD 2.0 API `cve` object (vulnerabilities[i].cve from a
        GET /rest/json/cves/2.0 response) onto the existing cves row with
        the matching cve_id — enrichment only ever fills in an
        already-upserted row (agent_service._sync_vulnerabilities creates
        the row itself, with just cve_id + severity from the distro
        advisory). Returns "OK" or "NOT_FOUND" for the caller's tally.

        Deliberately does NOT invent a `title` — NVD 2.0 records don't
        reliably carry one distinct from the description, and this
        codebase's rule throughout is never to fabricate a field just
        because the UI has a column for it (docs/compliance's
        "_sync_vulnerabilities" docstring states the same principle for
        distro advisory data).
        """
        cve_id = cve_data["id"]
        row = (await self.db.execute(select(CVE).where(CVE.cve_id == cve_id))).scalar_one_or_none()
        if row is None:
            return "NOT_FOUND"

        descriptions = cve_data.get("descriptions") or []
        en_desc = next((d["value"] for d in descriptions if d.get("lang") == "en"), None)
        if en_desc:
            row.description = en_desc

        metrics = cve_data.get("metrics") or {}
        cvss_data = None
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            entries = metrics.get(key)
            if entries:
                cvss_data = entries[0].get("cvssData")
                break
        if cvss_data:
            row.cvss_v3_score = cvss_data.get("baseScore")
            row.cvss_v3_severity = cvss_data.get("baseSeverity")

        cwe_ids = sorted({
            w["value"]
            for weakness in (cve_data.get("weaknesses") or [])
            for w in weakness.get("description", [])
            if w.get("value", "").startswith("CWE-")
        })
        if cwe_ids:
            row.cwe_ids = cwe_ids

        published = cve_data.get("published")
        if published:
            row.published_date = date.fromisoformat(published[:10])
        last_modified = cve_data.get("lastModified")
        if last_modified:
            row.updated_date = date.fromisoformat(last_modified[:10])

        row.nvd_url = f"https://nvd.nist.gov/vuln/detail/{cve_id}"
        row.enrichment_status = "OK"
        row.last_enriched_at = datetime.now(timezone.utc)
        await self.db.commit()
        return "OK"
