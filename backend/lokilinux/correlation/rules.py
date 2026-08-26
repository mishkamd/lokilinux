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

# Conditions must reference signal types the detector registry can actually
# emit (backend/lokilinux/signals/detectors.py: DETECTORS + _METRIC_RULES) —
# a rule referencing anything else can never reach threshold_score. See
# test_default_rules_are_reachable, which asserts this for every entry here.
DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "name": "host_down",
        "window_seconds": 300,
        "group_by": ["host_id"],
        "conditions": [{"signal": "host.unreachable", "weight": 100}],
        "threshold_score": 100,
        "incident_type": "host_down",
        "incident_severity": "CRITICAL",
    },
    {
        "name": "host_resource_exhaustion",
        "window_seconds": 300,
        "group_by": ["host_id"],
        # 30 each: any 2 of {cpu,memory,disk} sustained together cross 50;
        # one alone (30) does not — a single busy metric isn't an incident.
        "conditions": [
            {"signal": "cpu.high", "weight": 30},
            {"signal": "memory.high", "weight": 30},
            {"signal": "disk.usage.high", "weight": 30},
        ],
        "threshold_score": 50,
        "incident_type": "host_resource_exhaustion",
        "incident_severity": "HIGH",
    },
]


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
    """Insert-if-absent bootstrap for DEFAULT_RULES."""
    for spec in DEFAULT_RULES:
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
