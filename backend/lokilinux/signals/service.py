"""
LokiLinux — SignalService: dedup/upsert signals from detected occurrences.

upsert_signal is race-safe (single INSERT ... ON CONFLICT DO UPDATE
RETURNING, not a SELECT-then-write) — concurrent detections of the same
fingerprint from different events never lose an occurrence_count increment.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from lokilinux.events.fingerprint import fingerprint
from lokilinux.nats_topics import SIGNAL_DETECTED, SIGNAL_RESOLVED
from lokilinux.signals.detectors import DetectedSignal
from lokilinux.signals.models import Signal
from lokilinux.signals.repository import SignalOccurrenceRepository

logger = structlog.get_logger()

_TENANT_ID = "default"
_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _rank_expr(column: Any):
    return case(*[(column == sev, rank) for sev, rank in _SEVERITY_RANK.items()], else_=0)


def _safe_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


class SignalService:
    def __init__(self, db: AsyncSession, nats: Any, occurrences: SignalOccurrenceRepository) -> None:
        self.db = db
        self.nats = nats
        self.occurrences = occurrences

    async def upsert_signal(self, detected: DetectedSignal, *, tenant_id: str = _TENANT_ID) -> Signal:
        now = datetime.now(timezone.utc)
        fp = fingerprint(tenant_id, detected.host_id, detected.type, detected.resource)
        host_uuid = _safe_uuid(detected.host_id)

        stmt = pg_insert(Signal).values(
            tenant_id=tenant_id,
            type=detected.type,
            severity=detected.severity,
            status="OPEN",
            host_id=host_uuid,
            service=detected.service,
            fingerprint=fp,
            occurrence_count=1,
            first_seen=now,
            last_seen=now,
            metadata_=detected.metadata,
        )
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "fingerprint"],
            set_={
                "occurrence_count": Signal.occurrence_count + 1,
                "last_seen": excluded.last_seen,
                "status": "OPEN",
                "severity": case(
                    (_rank_expr(excluded.severity) > _rank_expr(Signal.severity), excluded.severity),
                    else_=Signal.severity,
                ),
            },
        ).returning(Signal)

        # populate_existing: without it, a second upsert for the same
        # fingerprint returns the ALREADY-in-session Python object with its
        # stale pre-update attributes (occurrence_count etc.) instead of the
        # fresh values RETURNING just gave back — a session-identity-map
        # gotcha with ORM-enabled INSERT...ON CONFLICT.
        result = await self.db.execute(stmt.execution_options(populate_existing=True))
        row = result.scalars().one()
        await self.db.commit()

        await self.occurrences.add(
            timestamp=now, tenant_id=tenant_id, signal_type=detected.type, severity=row.severity,
            host_id=detected.host_id, service=detected.service, fingerprint=fp,
            value=detected.value, metadata=detected.metadata,
        )
        try:
            await self.nats.publish(
                SIGNAL_DETECTED,
                _signal_event_json(row, fp),
            )
        except Exception:
            logger.error("signal.publish_failed", fingerprint=fp, exc_info=True)
        return row

    async def resolve_by_fingerprint(self, tenant_id: str, host_id: str | None, signal_type: str) -> None:
        """Used by the host.heartbeat.ok recovery hook — resolves any OPEN
        signal of `signal_type` for this host (e.g. host.unreachable)."""
        fp = fingerprint(tenant_id, host_id, signal_type, None)
        from sqlalchemy import select, update

        row = (
            await self.db.execute(
                select(Signal).where(Signal.tenant_id == tenant_id, Signal.fingerprint == fp, Signal.status == "OPEN")
            )
        ).scalar_one_or_none()
        if row is None:
            return
        await self.db.execute(
            update(Signal).where(Signal.id == row.id).values(status="RESOLVED")
        )
        await self.db.commit()
        try:
            await self.nats.publish(
                SIGNAL_RESOLVED,
                _signal_event_json(row, fp, status="RESOLVED"),
            )
        except Exception:
            logger.error("signal.resolve_publish_failed", fingerprint=fp, exc_info=True)


def _signal_event_json(row: Signal, fp: str, *, status: str | None = None) -> bytes:
    import json

    return json.dumps({
        "signal_id": str(row.id),
        "type": row.type,
        "severity": row.severity,
        "host_id": str(row.host_id) if row.host_id else None,
        "fingerprint": fp,
        "occurrence_count": row.occurrence_count,
        "status": status or row.status,
    }).encode()
