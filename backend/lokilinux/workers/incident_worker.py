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

import asyncio
import json
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from lokilinux.incidents.models import Incident, IncidentSignal
from lokilinux.incidents.service import IncidentService
from lokilinux.nats_topics import INCIDENT_CREATED, SIGNAL_RESOLVED
from lokilinux.runbooks.service import maybe_auto_run
from lokilinux.settings_schema import get_setting_value
from lokilinux.signals.models import Signal
from lokilinux.utils import liveness

logger = structlog.get_logger()

_SWEEP_INTERVAL_SECONDS = 60
_SWEEP_BATCH = 1000
_OPEN_STATUSES = ("OPEN", "ACKNOWLEDGED", "IN_PROGRESS")


class IncidentWorker:
    def __init__(self, nats_client, db_session_factory, cache, ch, storage) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache
        self.ch = ch
        self.storage = storage
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
            liveness.beat("incident_worker")
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
                svc = IncidentService(db, self.nats, self.cache, self.ch)
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
                    db, self.cache, self.storage, incident_type, incident_severity,
                    autorun_enabled=autorun_enabled, nats=self.nats,
                )
        except Exception:
            logger.error("incident_worker.runbook_matcher_failed", exc_info=True)

    async def _sweep(self) -> None:
        async with self.db_factory() as db:
            # shortcut: bounded sweep. An incident that stays open never changes updated_at, so
            # with more than _SWEEP_BATCH of them the newest ones are not checked; page by id
            # or keep a sweep cursor if that many incidents can really be open at once.
            open_incidents = (
                await db.execute(
                    select(Incident)
                    .where(Incident.status.in_(_OPEN_STATUSES))
                    .order_by(Incident.updated_at.asc())
                    .limit(_SWEEP_BATCH)
                )
            ).scalars().all()
            if not open_incidents:
                return
            svc = IncidentService(db, self.nats, self.cache, self.ch)
            # Ids first: a rollback below expires every loaded row, and reading .id off an
            # expired row would try to reload it outside the async context.
            for incident_id in [i.id for i in open_incidents]:
                try:
                    resolved = await svc.maybe_auto_resolve(incident_id)
                except Exception:
                    # One bad incident must not stop the rest of the sweep.
                    logger.error(
                        "incident.sweep_failed", incident_id=str(incident_id), exc_info=True
                    )
                    await db.rollback()
                    continue
                if resolved:
                    logger.info(
                        "incident.auto_resolved_by_sweep", incident_id=str(incident_id),
                        swept_at=str(datetime.now(timezone.utc)),
                    )
