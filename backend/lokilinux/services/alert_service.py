"""
LokiLinux — AlertService: create, acknowledge, resolve, and list alerts.

Alert.status uses plain strings: ACTIVE / ACKNOWLEDGED / RESOLVED / EXPIRED.
Alert.acknowledged_by is UUID; Better Auth may use nanoid user IDs — conversion
is attempted and silently skipped on failure (ponytail: model inconsistency from
Val 2 design; unify to String(255) in Val 3 migration).
"""

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.alert import Alert, AlertRule
from lokilinux.nats_topics import ALERT_CREATED

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(self, db: AsyncSession, nats=None) -> None:
        self.db = db
        self.nats = nats

    async def create_alert(
        self,
        title: str,
        description: str,
        severity: str,
        agent_id: UUID | None = None,
        rule_id: UUID | None = None,
        alert_type: str | None = None,
    ) -> Alert | None:
        """Insert a new ACTIVE alert, deduped on (agent_id, alert_type) against
        uq_alerts_active_agent_type (migration 022) — without this, a
        recurring condition (e.g. an agent stuck offline, swept every 60s by
        HeartbeatMonitorWorker) inserts a fresh row every cycle forever.
        Confirmed live: one flapping agent had accumulated 64 identical
        AGENT_OFFLINE alerts. Returns None when a matching ACTIVE alert
        already exists — the caller must not re-publish ALERT_CREATED in
        that case, or NotificationWorker would re-notify every cycle for an
        already-known condition.
        """
        stmt = (
            pg_insert(Alert)
            .values(
                title=title,
                description=description,
                severity=severity.upper(),
                agent_id=agent_id,
                rule_id=rule_id,
                alert_type=alert_type,
                status="ACTIVE",
            )
            .on_conflict_do_nothing(
                index_elements=["agent_id", "alert_type"],
                index_where=(Alert.status == "ACTIVE"),
            )
            .returning(Alert)
        )
        alert = (await self.db.execute(stmt)).scalar_one_or_none()
        await self.db.commit()

        if alert is None:
            return None

        if self.nats:
            try:
                await self.nats.publish(
                    ALERT_CREATED,
                    json.dumps({"alert_id": str(alert.id), "severity": severity}).encode(),
                )
            except Exception:
                logger.warning("NATS publish failed for alert.created", exc_info=True)

        return alert

    async def resolve_agent_offline_alerts(self, agent_id: UUID) -> None:
        """Auto-resolve ACTIVE AGENT_OFFLINE alerts when an agent's heartbeat
        recovers — called from AgentService.update_heartbeat on the
        INACTIVE/UNHEALTHY -> ACTIVE transition. Without this nothing ever
        closes the alert; confirmed live: both fleet agents were healthy and
        heartbeating but still carried 68 ACTIVE AGENT_OFFLINE alerts between
        them.
        """
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(Alert).where(
                Alert.agent_id == agent_id,
                Alert.alert_type == "AGENT_OFFLINE",
                Alert.status == "ACTIVE",
            )
        )
        for alert in result.scalars().all():
            alert.status = "RESOLVED"
            alert.resolved_at = now
        await self.db.commit()

    async def acknowledge(self, alert_id: UUID, user_id: str) -> Alert:
        alert = await self.db.get(Alert, alert_id)
        if not alert:
            raise ValueError(f"Alert {alert_id} not found")
        alert.status = "ACKNOWLEDGED"
        alert.acknowledged_at = datetime.now(timezone.utc)
        # ponytail: acknowledged_by is UUID in model; skip if user_id is nanoid
        try:
            alert.acknowledged_by = UUID(user_id)
        except ValueError:
            pass
        await self.db.commit()
        return alert

    async def resolve(self, alert_id: UUID, user_id: str | None = None) -> Alert:
        alert = await self.db.get(Alert, alert_id)
        if not alert:
            raise ValueError(f"Alert {alert_id} not found")
        alert.status = "RESOLVED"
        alert.resolved_at = datetime.now(timezone.utc)
        if user_id:
            try:
                alert.resolved_by = UUID(user_id)
            except ValueError:
                pass
        await self.db.commit()
        return alert

    async def list_alerts(
        self,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 20,
    ) -> dict:
        filters = []
        if status:
            filters.append(Alert.status == status.upper())
        if severity:
            filters.append(Alert.severity == severity.upper())

        count_query = select(func.count()).select_from(Alert).where(*filters)
        total = (await self.db.execute(count_query)).scalar_one()

        query = select(Alert).where(*filters).order_by(Alert.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        alerts = result.scalars().all()
        return {"items": alerts, "next_cursor": None, "total": total}

    async def create_rule(
        self,
        name: str,
        conditions: dict,
        description: str | None = None,
        severity: str | None = None,
        notification_channels: dict | None = None,
        is_enabled: bool = True,
        created_by: UUID | None = None,
    ) -> AlertRule:
        rule = AlertRule(
            name=name,
            description=description,
            conditions=conditions,
            alert_severity=severity.upper() if severity else None,
            notification_channels=notification_channels,
            is_enabled=is_enabled,
            created_by=created_by,
        )
        self.db.add(rule)
        await self.db.commit()
        await self.db.refresh(rule)
        return rule

    async def list_rules(self) -> dict:
        result = await self.db.execute(
            select(AlertRule).where(AlertRule.is_enabled.is_(True)).order_by(AlertRule.created_at.desc())
        )
        rules = result.scalars().all()
        return {"items": rules, "total": len(rules)}
