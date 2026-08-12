"""
LokiLinux — CVEService: per-agent vulnerability queries with cache-aside.

AgentVulnerability.cve_id is String(50) FK to cves.cve_id (not cves.id).
AgentVulnerability.severity is the denormalized severity column on the vuln row.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import TTL_CVE_DATA, RedisCache
from lokilinux.models.cve import CVE, AgentVulnerability


class CVEService:
    def __init__(self, db: AsyncSession, cache: RedisCache) -> None:
        self.db = db
        self.cache = cache

    async def get_agent_vulnerabilities(
        self, agent_id: UUID, severity: str | None = None
    ) -> list[dict]:
        """Return vulnerability records for an agent, optionally filtered by severity."""
        cache_key = f"vulnerability:{agent_id}:{severity or 'all'}"
        cached = await self.cache.get_cached(cache_key)
        if cached is not None:
            return cached

        query = (
            select(AgentVulnerability, CVE)
            .join(CVE, AgentVulnerability.cve_id == CVE.cve_id)
            .where(AgentVulnerability.agent_id == agent_id)
        )
        if severity:
            query = query.where(AgentVulnerability.severity == severity)

        result = await self.db.execute(query)
        # Serialize to dicts — ORM objects are not JSON-serialisable
        rows = [
            {
                "vuln_id": v.id,
                "cve_id": v.cve_id,
                "package_name": v.package_name,
                "package_version": v.package_version,
                "severity": v.severity,
                "cvss_score": v.cvss_score,
                "fix_available": v.fix_available,
                "is_remediated": v.is_remediated,
            }
            for v, _ in result.all()
        ]
        await self.cache.set_cached(cache_key, rows, TTL_CVE_DATA)
        return rows

    async def import_nvd_cve(self, cve_data: dict) -> None:
        # ponytail: full NVD import stubbed; wire up in Phase 3 (cve-sync worker)
        pass
