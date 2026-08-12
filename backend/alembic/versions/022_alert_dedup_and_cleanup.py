"""Dedup recurring alerts + retroactively resolve stale ones + partial unique index.

Revision ID: 022
Create Date: 2026-08-01

Confirmed live: HeartbeatMonitorWorker sweeps every 60s and AlertService.
create_alert had no dedup, so one agent stuck offline had accumulated 64
identical AGENT_OFFLINE alerts, and nothing ever auto-resolved them once the
agent recovered — both fleet agents were healthy/heartbeating but still
carried 68 ACTIVE alerts between them.

Order matters: the partial unique index cannot be created while duplicate
(agent_id, alert_type) ACTIVE rows exist, so cleanup runs first.
"""

import sqlalchemy as sa

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Collapse duplicates: keep only the most recent ACTIVE alert per
    # (agent_id, alert_type); older ones become RESOLVED (history kept, not
    # deleted). Robust regardless of current agent health.
    op.execute(sa.text("""
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY agent_id, alert_type
                ORDER BY triggered_at DESC, id DESC
            ) AS rn
            FROM alerts
            WHERE status = 'ACTIVE' AND agent_id IS NOT NULL AND alert_type IS NOT NULL
        )
        UPDATE alerts SET status = 'RESOLVED', resolved_at = now()
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
    """))

    # 2. Retroactive auto-resolve: an AGENT_OFFLINE alert is stale once its
    # agent is ACTIVE again — exactly what the new update_heartbeat hook does
    # going forward. Scoped to AGENT_OFFLINE since that's the only alert_type
    # actually produced today; other types have no such "recovered" signal.
    op.execute(sa.text("""
        UPDATE alerts SET status = 'RESOLVED', resolved_at = now()
        WHERE status = 'ACTIVE' AND alert_type = 'AGENT_OFFLINE'
          AND agent_id IN (SELECT id FROM agents WHERE status = 'ACTIVE')
    """))

    # 3. Partial unique index — same technique as uq_jobs_dedup_key in
    # 020_scope_job_dedup_to_active.py. NULLs in agent_id/alert_type are
    # never considered equal by Postgres, so non-AGENT_OFFLINE alert types
    # without an agent are unaffected.
    op.create_index(
        "uq_alerts_active_agent_type",
        "alerts",
        ["agent_id", "alert_type"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_active_agent_type", table_name="alerts")
