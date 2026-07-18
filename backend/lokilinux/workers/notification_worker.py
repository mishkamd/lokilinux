"""
LokiLinux — NotificationWorker: delivers alerts to SMTP/Slack.

Subscribes to lokilinux.alert.created (already published by
AlertService.create_alert — this worker is the first consumer of it).
Reads delivery config from notifications.* settings; if neither smtp_host
nor slack_webhook_url is configured, this is a no-op. Best-effort — delivery
failures are logged, never raised (a broken webhook shouldn't crash alerting).
"""

import asyncio
import json
import smtplib
from email.mime.text import MIMEText
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select

from lokilinux.models.alert import Alert
from lokilinux.nats_topics import ALERT_CREATED
from lokilinux.settings_schema import get_all_settings, get_setting_value

logger = structlog.get_logger()


class NotificationWorker:
    def __init__(self, nats_client, db_session_factory) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory

    async def start(self) -> None:
        await self.nats.subscribe(ALERT_CREATED, cb=self._handle_alert_created)
        logger.info("NotificationWorker started")

    async def _handle_alert_created(self, msg) -> None:
        try:
            data = json.loads(msg.data)
            alert_id = UUID(data["alert_id"])
            async with self.db_factory() as db:
                alert = (await db.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
                if not alert:
                    return
                cfg = (await get_all_settings(db, groups={"notifications"}))["notifications"]
                # get_all_settings masks secrets for display — pull the real value for actual delivery
                cfg["smtp_password"] = await get_setting_value(db, "notifications.smtp_password")

            subject = f"[{alert.severity}] {alert.title}"
            body = alert.description or alert.title

            if cfg.get("smtp_host") and cfg.get("smtp_from"):
                # smtplib is blocking — run off the event loop so SMTP latency
                # doesn't stall heartbeats/jobs and other NATS callbacks.
                await asyncio.to_thread(self._send_email, cfg, subject, body)
            if cfg.get("slack_webhook_url"):
                await self._send_slack(cfg["slack_webhook_url"], subject, body)
        except Exception:
            logger.error("notification_worker.delivery_failed", exc_info=True)

    def _send_email(self, cfg: dict, subject: str, body: str) -> None:
        try:
            message = MIMEText(body)
            message["Subject"] = subject
            message["From"] = cfg["smtp_from"]
            message["To"] = cfg["smtp_from"]  # ponytail: no per-alert recipient list yet — sends to the configured from-address
            with smtplib.SMTP(cfg["smtp_host"], int(cfg.get("smtp_port") or 587), timeout=10) as server:
                server.starttls()
                if cfg.get("smtp_user"):
                    server.login(cfg["smtp_user"], cfg.get("smtp_password") or "")
                server.send_message(message)
        except Exception:
            logger.warning("notification_worker.smtp_failed", exc_info=True)

    async def _send_slack(self, webhook_url: str, subject: str, body: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(webhook_url, json={"text": f"*{subject}*\n{body}"})
        except Exception:
            logger.warning("notification_worker.slack_failed", exc_info=True)
