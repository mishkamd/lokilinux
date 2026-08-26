"""
LokiLinux — incident timeline entry helper.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.incidents.models import IncidentTimeline


async def add_entry(
    db: AsyncSession, incident_id: UUID, kind: str, message: str, payload: dict[str, Any] | None = None
) -> IncidentTimeline:
    entry = IncidentTimeline(incident_id=incident_id, kind=kind, message=message, payload=payload or {})
    db.add(entry)
    await db.flush()
    return entry
