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

from sqlalchemy import select
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
    ) -> Alert:
        alert = Alert(
            title=title,
            description=description,
            severity=severity.upper(),
            agent_id=agent_id,
            rule_id=rule_id,
            alert_type=alert_type,
            status="ACTIVE",
        )
        self.db.add(alert)
        await self.db.commit()

        if self.nats:
            try:
                await self.nats.publish(
                    ALERT_CREATED,
                    json.dumps({"alert_id": str(alert.id), "severity": severity}).encode(),
                )
            except Exception:
                logger.warning("NATS publish failed for alert.created", exc_info=True)

        return alert

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
        query = select(Alert)
        if status:
            query = query.where(Alert.status == status.upper())
        if severity:
            query = query.where(Alert.severity == severity.upper())
        query = query.order_by(Alert.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        alerts = result.scalars().all()
        return {"items": alerts, "next_cursor": None, "total": len(alerts)}

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
