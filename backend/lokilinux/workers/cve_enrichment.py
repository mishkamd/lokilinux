"""
LokiLinux — CVEEnrichmentWorker: fills in CVSS/title/description/CWE/dates
on `cves` rows from the NVD 2.0 API, and actively-exploited/KEV-date from
CISA's Known Exploited Vulnerabilities catalog (docs/vulnerabilities V3).

Same shape as RemediationSchedulerWorker — its own asyncio loop, no leader
election. Every API replica runs this loop; pg_try_advisory_lock (session-
scoped, released at the end of each tick) is the guard against two
replicas hitting NVD's rate limit simultaneously — only the replica that
acquires the lock does work that tick, everyone else skips.

Two passes per tick, cheapest first:
  1. Backfill — one CVE at a time from `cves` rows still
     enrichment_status='PENDING' (agent_service._sync_vulnerabilities sets
     this on every new row). Reusable across restarts: a crashed run just
     leaves rows PENDING, the next tick picks up where it left off instead
     of re-querying anything already OK.
  2. Staleness refresh — re-queries the handful of enrichment_status='OK'
     rows with the oldest last_enriched_at, past _STALE_AFTER, one CVE at
     a time via the same per-CVE lookup as the backfill (not NVD's bulk
     lastModStartDate/lastModEndDate range endpoint — this app's CVE count
     is small enough that a per-row refresh is simpler and reuses
     _enrich_one exactly, at the cost of one extra request per stale row
     instead of one bulk page covering many). A CVE NVD later revises
     (CVSS assigned, description clarified) eventually gets picked up
     without ever being marked PENDING again.

CISA KEV is a separate, much cheaper fetch (one ~1MB JSON, no per-CVE
calls) run on a longer cadence via its own tick counter.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select, text

from lokilinux.models.cve import CVE
from lokilinux.services.cve_service import CVEService
from lokilinux.settings_schema import get_setting_value

logger = structlog.get_logger()

_TICK_SECONDS = 10
_BACKFILL_BATCH = 3  # per tick — 3 req / 10s stays under NVD's unauthenticated 5 req/30s
_STALE_AFTER = timedelta(days=30)
_STALE_REFRESH_BATCH = 1  # small — this runs after backfill in the same rate-limit budget
_KEV_EVERY_N_TICKS = 720  # ~2 hours at a 10s tick
_ADVISORY_LOCK_KEY = 0x4C4B4C7645 & 0x7FFFFFFFFFFFFFFF  # "LKLVE" — arbitrary, just needs to be stable and unique in this app
_NVD_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


class CVEEnrichmentWorker:
    def __init__(self, db_session_factory, cache) -> None:
        self.db_factory = db_session_factory
        self.cache = cache
        self._task: asyncio.Task | None = None
        self._tick_count = 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("CVEEnrichmentWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.error("cve_enrichment.tick_failed", exc_info=True)
            self._tick_count += 1
            await asyncio.sleep(_TICK_SECONDS)

    async def _tick(self) -> None:
        async with self.db_factory() as db:
            got_lock = (
                await db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
            ).scalar()
            if not got_lock:
                return  # another replica is already working this tick
            try:
                api_key = await get_setting_value(db, "cve.nvd_api_key") or None
                async with httpx.AsyncClient(timeout=15) as client:
                    await self._backfill_pending(db, client, api_key)
                    await self._refresh_stale(db, client, api_key)
                    if self._tick_count % _KEV_EVERY_N_TICKS == 0:
                        await self._sync_kev(db, client)
            finally:
                await db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
                await db.commit()

    async def _backfill_pending(self, db, client: httpx.AsyncClient, api_key: str | None) -> None:
        pending = (
            await db.execute(
                select(CVE.cve_id).where(CVE.enrichment_status == "PENDING").limit(_BACKFILL_BATCH)
            )
        ).scalars().all()
        if not pending:
            return

        svc = CVEService(db, self.cache)
        for cve_id in pending:
            outcome = await self._enrich_one(db, client, svc, cve_id, api_key)
            logger.info("cve_enrichment.backfill", cve_id=cve_id, outcome=outcome)

    async def _refresh_stale(self, db, client: httpx.AsyncClient, api_key: str | None) -> None:
        cutoff = datetime.now(timezone.utc) - _STALE_AFTER
        stale = (
            await db.execute(
                select(CVE.cve_id)
                .where(CVE.enrichment_status == "OK", CVE.last_enriched_at < cutoff)
                .order_by(CVE.last_enriched_at)
                .limit(_STALE_REFRESH_BATCH)
            )
        ).scalars().all()
        if not stale:
            return

        svc = CVEService(db, self.cache)
        for cve_id in stale:
            outcome = await self._enrich_one(db, client, svc, cve_id, api_key)
            logger.info("cve_enrichment.stale_refresh", cve_id=cve_id, outcome=outcome)

    async def _enrich_one(
        self, db, client: httpx.AsyncClient, svc: CVEService, cve_id: str, api_key: str | None
    ) -> str:
        headers = {"apiKey": api_key} if api_key else {}
        try:
            resp = await client.get(_NVD_BASE, params={"cveId": cve_id}, headers=headers)
        except httpx.RequestError as exc:
            # Network-level failure — transient, worth retrying next tick.
            # Leave enrichment_status untouched (still PENDING) so it's
            # picked up again rather than parked as a permanent ERROR.
            logger.warning("cve_enrichment.request_failed", cve_id=cve_id, error=str(exc))
            return "RETRY"

        if resp.status_code in (403, 429):
            # Rate-limited — back off the rest of this tick rather than
            # burning through the remaining batch and getting a longer ban.
            logger.warning("cve_enrichment.rate_limited", status=resp.status_code)
            await asyncio.sleep(6)
            return "RATE_LIMITED"

        if resp.status_code != 200:
            # Anything else (malformed request, NVD-side error) — mark
            # ERROR rather than retrying forever on a CVE ID NVD will never
            # accept.
            row = (await db.execute(select(CVE).where(CVE.cve_id == cve_id))).scalar_one_or_none()
            if row:
                row.enrichment_status = "ERROR"
                row.last_enriched_at = datetime.now(timezone.utc)
                await db.commit()
            return f"ERROR({resp.status_code})"

        data = resp.json()
        vulns = data.get("vulnerabilities") or []
        if not vulns:
            row = (await db.execute(select(CVE).where(CVE.cve_id == cve_id))).scalar_one_or_none()
            if row:
                row.enrichment_status = "NOT_FOUND"
                row.last_enriched_at = datetime.now(timezone.utc)
                await db.commit()
            return "NOT_FOUND"

        return await svc.import_nvd_cve(vulns[0]["cve"])

    async def _sync_kev(self, db, client: httpx.AsyncClient) -> None:
        try:
            resp = await client.get(_KEV_URL, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("cve_enrichment.kev_fetch_failed", error=str(exc))
            return

        entries = {v["cveID"]: v.get("dateAdded") for v in resp.json().get("vulnerabilities", [])}
        if not entries:
            return

        rows = (await db.execute(select(CVE).where(CVE.cve_id.in_(entries.keys())))).scalars().all()
        for row in rows:
            row.is_actively_exploited = True
            date_added = entries.get(row.cve_id)
            if date_added:
                from datetime import date as _date
                row.kev_date_added = _date.fromisoformat(date_added)
        await db.commit()
        logger.info("cve_enrichment.kev_synced", matched=len(rows), kev_total=len(entries))
