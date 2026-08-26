"""
LokiLinux — correlation rule cache + default seed rule.

RuleCache is an in-memory snapshot of enabled rules, refreshed at most every
RULE_CACHE_TTL_SEC — correlation runs on the signal-detection hot path, so
hitting Postgres on every single signal would be wasteful for something that
changes rarely (an admin editing rules in the UI, Task F1).
"""

from datetime import datetime, timezone
from typing import Any
import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.signals.models import CorrelationRule

RULE_CACHE_TTL_SEC = 30

DEFAULT_RULE_APPLICATION_DEGRADATION: dict[str, Any] = {
    "name": "application_degradation",
    "window_seconds": 300,
    "group_by": ["host_id"],
    "conditions": [
        {"signal": "cpu.high", "weight": 20},
        {"signal": "load.high", "weight": 20},
        {"signal": "http.latency.high", "weight": 25},
        {"signal": "http.error_rate.high", "weight": 35},
    ],
    "threshold_score": 60,
    "incident_type": "application_degradation",
    "incident_severity": "CRITICAL",
}


class RuleCache:
    def __init__(self) -> None:
        self._rules: list[CorrelationRule] = []
        self._loaded_at: float = 0.0

    async def get_enabled_rules(self, db: AsyncSession) -> list[CorrelationRule]:
        if self._rules and (time.monotonic() - self._loaded_at) < RULE_CACHE_TTL_SEC:
            return self._rules
        rows = (
            await db.execute(select(CorrelationRule).where(CorrelationRule.enabled.is_(True)))
        ).scalars().all()
        self._rules = list(rows)
        self._loaded_at = time.monotonic()
        return self._rules


async def ensure_default_rules(db: AsyncSession, *, tenant_id: str = "default") -> None:
    """Insert-if-absent bootstrap for DEFAULT_RULE_APPLICATION_DEGRADATION."""
    spec = DEFAULT_RULE_APPLICATION_DEGRADATION
    stmt = (
        pg_insert(CorrelationRule)
        .values(
            tenant_id=tenant_id,
            name=spec["name"],
            enabled=True,
            window_seconds=spec["window_seconds"],
            group_by=spec["group_by"],
            conditions=spec["conditions"],
            threshold_score=spec["threshold_score"],
            incident_type=spec["incident_type"],
            incident_severity=spec["incident_severity"],
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "name"])
    )
    await db.execute(stmt)
    await db.commit()
