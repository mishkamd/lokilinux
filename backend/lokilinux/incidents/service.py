"""
LokiLinux — IncidentService: lifecycle, dedup, alert bridge, auto-resolve.

Backward-compat bridge (plan decision 6): every NEW incident also creates an
Alert through the existing AlertService.create_alert — /alerts and
NotificationWorker keep working completely unmodified, they just see one
more ALERT_CREATED with a title prefixed "Incident:". Re-attaching a signal
to an already-open incident (the common case, since a correlation window
keeps re-firing candidates as more signals join) does NOT create another
alert — only the very first open does.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID
import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from lokilinux.correlation.evaluator import IncidentCandidate
from lokilinux.events.fingerprint import fingerprint
from lokilinux.incidents.lifecycle import assert_legal
from lokilinux.incidents.models import Incident, IncidentSignal
from lokilinux.incidents.timeline import add_entry
from lokilinux.nats_topics import INCIDENT_CREATED, INCIDENT_RESOLVED, INCIDENT_UPDATED
from lokilinux.services.alert_service import AlertService
from lokilinux.signals.models import Signal

logger = structlog.get_logger()

_OPEN_STATUSES = ("OPEN", "ACKNOWLEDGED", "IN_PROGRESS")
_OPEN_LOCK_TTL_SEC = 10
INCIDENT_AUTO_RESOLVE_QUIET_SEC = 600


def _safe_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _incident_event_json(incident: Incident) -> bytes:
    return json.dumps({
        "incident_id": str(incident.id),
        "type": incident.type,
        "severity": incident.severity,
        "status": incident.status,
        "title": incident.title,
    }).encode()


class IncidentService:
    def __init__(self, db: AsyncSession, nats: Any, cache: Any) -> None:
        self.db = db
        self.nats = nats
        self.cache = cache

    async def _resolve_member_signals(self, candidate: IncidentCandidate, tenant_id: str) -> list[Signal]:
        host_id = candidate.group_values.get("host_id") or None
        fingerprints = [fingerprint(tenant_id, host_id, t, None) for t in candidate.member_types]
        rows = (
            await self.db.execute(
                select(Signal).where(Signal.tenant_id == tenant_id, Signal.fingerprint.in_(fingerprints))
            )
        ).scalars().all()
        return list(rows)

    async def open_from_candidate(self, candidate: IncidentCandidate, *, tenant_id: str = "default") -> Incident:
        # Best-effort race guard around the check-then-insert below — two
        # near-simultaneous candidates for the same group_key (redelivery,
        # or two signals crossing threshold within the same instant) must
        # not create two incidents. Not gating on the result: losing the
        # race just means we proceed to the SELECT, which will now see the
        # winner's row (same transaction isolation the rest of this app
        # relies on for read-after-write within a request).
        await self.cache.set_nx(f"lock:inc:{candidate.group_key}", ttl=_OPEN_LOCK_TTL_SEC)

        signal_rows = await self._resolve_member_signals(candidate, tenant_id)

        existing = (
            await self.db.execute(
                select(Incident).where(
                    Incident.tenant_id == tenant_id,
                    Incident.group_key == candidate.group_key,
                    Incident.status.in_(_OPEN_STATUSES),
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            for sig in signal_rows:
                await self.db.execute(
                    pg_insert(IncidentSignal)
                    .values(incident_id=existing.id, signal_id=sig.id)
                    .on_conflict_do_nothing(index_elements=["incident_id", "signal_id"])
                )
            await add_entry(
                self.db, existing.id, "signal",
                f"additional signal: {candidate.root_signal_type} (score {candidate.score})",
            )
            await self.db.commit()
            return existing

        host_id = candidate.group_values.get("host_id") or "fleet"
        title = f"{candidate.rule.incident_type.replace('_', ' ').title()}: {host_id}"
        confidence = (
            min(1.0, candidate.score / candidate.rule.threshold_score)
            if candidate.rule.threshold_score else 0.0
        )
        root_signal = next(
            (s for s in signal_rows if s.type == candidate.root_signal_type),
            signal_rows[0] if signal_rows else None,
        )

        incident = Incident(
            tenant_id=tenant_id,
            title=title,
            type=candidate.rule.incident_type,
            severity=candidate.rule.incident_severity,
            status="OPEN",
            root_cause_signal_id=root_signal.id if root_signal else None,
            confidence=confidence,
            group_key=candidate.group_key,
            correlation_rule_id=candidate.rule.id,
        )
        self.db.add(incident)
        await self.db.flush()

        for sig in signal_rows:
            self.db.add(IncidentSignal(incident_id=incident.id, signal_id=sig.id))
        await add_entry(
            self.db, incident.id, "created",
            f"opened from {candidate.rule.incident_type} (score {candidate.score})",
        )
        for sig in signal_rows:
            await add_entry(self.db, incident.id, "signal", f"contributing signal: {sig.type}")

        alert_svc = AlertService(self.db, self.nats)
        alert = await alert_svc.create_alert(
            title=f"Incident: {title}",
            description=f"Correlated incident opened from {len(signal_rows)} signal(s)",
            severity=candidate.rule.incident_severity,
            agent_id=_safe_uuid(host_id),
            alert_type=candidate.rule.incident_type.upper(),
        )
        if alert is not None:
            alert.incident_id = incident.id

        await self.db.commit()

        try:
            await self.nats.publish(INCIDENT_CREATED, _incident_event_json(incident))
        except Exception:
            logger.error("incident.publish_failed", incident_id=str(incident.id), exc_info=True)

        return incident

    async def _get(self, incident_id: UUID) -> Incident:
        incident = await self.db.get(Incident, incident_id)
        if incident is None:
            raise ValueError(f"incident {incident_id} not found")
        return incident

    async def _transition(self, incident_id: UUID, target: str, *, actor: Any = None) -> Incident:
        incident = await self._get(incident_id)
        assert_legal(incident.status, target)
        now = datetime.now(timezone.utc)
        incident.status = target
        incident.updated_at = now
        if target == "ACKNOWLEDGED":
            incident.acknowledged_at = now
        if target == "RESOLVED":
            incident.resolved_at = now
        kind = "REOPENED" if target == "OPEN" else "transition"
        await add_entry(self.db, incident.id, kind, target, payload={"by": str(actor) if actor else None})
        await self.db.commit()

        subject = INCIDENT_RESOLVED if target == "RESOLVED" else INCIDENT_UPDATED
        try:
            await self.nats.publish(subject, _incident_event_json(incident))
        except Exception:
            logger.error("incident.publish_failed", incident_id=str(incident.id), exc_info=True)
        return incident

    async def ack(self, incident_id: UUID, actor: Any = None) -> Incident:
        return await self._transition(incident_id, "ACKNOWLEDGED", actor=actor)

    async def resolve(self, incident_id: UUID, actor: Any = None) -> Incident:
        return await self._transition(incident_id, "RESOLVED", actor=actor)

    async def reopen(self, incident_id: UUID, actor: Any = None) -> Incident:
        return await self._transition(incident_id, "OPEN", actor=actor)

    async def maybe_auto_resolve(self, incident_id: UUID) -> bool:
        """All linked signals RESOLVED and quiet >= INCIDENT_AUTO_RESOLVE_QUIET_SEC -> resolve."""
        incident = await self._get(incident_id)
        if incident.status in ("RESOLVED", "CLOSED"):
            return False

        signal_ids = (
            await self.db.execute(
                select(IncidentSignal.signal_id).where(IncidentSignal.incident_id == incident.id)
            )
        ).scalars().all()
        if not signal_ids:
            return False

        signals = (await self.db.execute(select(Signal).where(Signal.id.in_(signal_ids)))).scalars().all()
        now = datetime.now(timezone.utc)
        all_quiet = all(
            s.status == "RESOLVED" and (now - s.last_seen).total_seconds() >= INCIDENT_AUTO_RESOLVE_QUIET_SEC
            for s in signals
        )
        if not all_quiet:
            return False

        await self._transition(incident.id, "RESOLVED", actor=None)
        await add_entry(self.db, incident.id, "note", "auto-resolved: all linked signals quiet")
        await self.db.commit()
        return True
