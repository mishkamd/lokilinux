"""
LokiLinux — IncidentWorker: watcher (SIGNAL_RESOLVED) + sweeper.

Same asyncio-loop shape as JobTimeoutWorker/HeartbeatMonitorWorker (no NATS
event marks "these signals have been quiet long enough" — absence isn't an
event). The SIGNAL_RESOLVED watcher fires the moment ONE signal resolves,
but IncidentService.maybe_auto_resolve's quiet-window gate (600s) means it
almost never resolves right then — that resolution happens later, in the
sweep, once enough time has actually passed. The watcher still matters: it
means resolution isn't purely on a 60s clock for the common case where a
signal resolves well after its incident's other signals already went quiet.
"""

from datetime import datetime, timezone
import asyncio
import json

from sqlalchemy import select
import structlog

from lokilinux.incidents.models import Incident, IncidentSignal
from lokilinux.incidents.service import IncidentService
from lokilinux.nats_topics import INCIDENT_CREATED, SIGNAL_RESOLVED
from lokilinux.runbooks.service import maybe_auto_run
from lokilinux.settings_schema import get_setting_value
from lokilinux.signals.models import Signal

logger = structlog.get_logger()

_SWEEP_INTERVAL_SECONDS = 60
_OPEN_STATUSES = ("OPEN", "ACKNOWLEDGED", "IN_PROGRESS")


class IncidentWorker:
    def __init__(self, nats_client, db_session_factory, cache) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.nats.subscribe(SIGNAL_RESOLVED, cb=self._handle_signal_resolved)
        await self.nats.subscribe(INCIDENT_CREATED, cb=self._handle_incident_created)
        self._task = asyncio.create_task(self._loop())
        logger.info("IncidentWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._sweep()
            except Exception:
                logger.error("incident_worker.sweep_failed", exc_info=True)
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)

    async def _handle_signal_resolved(self, msg) -> None:
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("incident_worker.malformed_json", exc_info=True)
            return
        fp = data.get("fingerprint")
        if not fp:
            return
        try:
            async with self.db_factory() as db:
                signal = (
                    await db.execute(select(Signal).where(Signal.fingerprint == fp))
                ).scalar_one_or_none()
                if signal is None:
                    return
                incident_ids = (
                    await db.execute(
                        select(IncidentSignal.incident_id).where(IncidentSignal.signal_id == signal.id)
                    )
                ).scalars().all()
                if not incident_ids:
                    return
                svc = IncidentService(db, self.nats, self.cache)
                for incident_id in incident_ids:
                    await svc.maybe_auto_resolve(incident_id)
        except Exception:
            logger.error("incident_worker.signal_resolved_handling_failed", exc_info=True)

    async def _handle_incident_created(self, msg) -> None:
        """Runbook matcher (Task E2): AUTO-mode runbooks whose incident_type
        matches and min_severity is at or below this incident's severity
        run immediately, gated by the global kill switch — MANUAL runbooks
        are untouched, they only run through the explicit execute endpoint."""
        try:
            data = json.loads(msg.data)
        except Exception:
            logger.error("incident_worker.malformed_incident_created_json", exc_info=True)
            return
        incident_type = data.get("type")
        incident_severity = data.get("severity")
        if not incident_type or not incident_severity:
            return
        try:
            async with self.db_factory() as db:
                autorun_enabled = await get_setting_value(db, "observability.incident_autorun_runbooks")
                if not autorun_enabled:
                    return
                await maybe_auto_run(
                    db, self.cache, incident_type, incident_severity,
                    autorun_enabled=autorun_enabled, nats=self.nats,
                )
        except Exception:
            logger.error("incident_worker.runbook_matcher_failed", exc_info=True)

    async def _sweep(self) -> None:
        async with self.db_factory() as db:
            open_incidents = (
                await db.execute(select(Incident).where(Incident.status.in_(_OPEN_STATUSES)))
            ).scalars().all()
            if not open_incidents:
                return
            svc = IncidentService(db, self.nats, self.cache)
            for incident in open_incidents:
                resolved = await svc.maybe_auto_resolve(incident.id)
                if resolved:
                    logger.info(
                        "incident.auto_resolved_by_sweep", incident_id=str(incident.id),
                        swept_at=str(datetime.now(timezone.utc)),
                    )
