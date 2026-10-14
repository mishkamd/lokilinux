"""incidents — at most one open incident per (tenant_id, group_key) (ROADMAP M5).

open_from_candidate used a check-then-insert, with a best-effort Redis lock.
Two workers could both see no open incident and both insert. The partial
unique index makes the database the arbiter; the loser now attaches to the
winner (incidents/service.py).

Pre-existing duplicates would make the index fail. This migration refuses to
run instead of rewriting incident state: resolve the listed groups first.

Revision ID: 049
Create Date: 2026-10-14
"""

import sqlalchemy as sa

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None

_OPEN = "('OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS')"


def upgrade() -> None:
    dupes = op.get_bind().execute(sa.text(
        "SELECT tenant_id, group_key, count(*) FROM incidents "
        f"WHERE status IN {_OPEN} AND group_key IS NOT NULL "
        "GROUP BY tenant_id, group_key HAVING count(*) > 1"
    )).fetchall()
    if dupes:
        listed = "; ".join(f"{t}/{g} x{n}" for t, g, n in dupes[:20])
        raise RuntimeError(
            "migration 049 blocked: open incidents share a group_key "
            f"({listed}). Resolve the extra rows, then re-run migrate."
        )
    op.execute(
        "CREATE UNIQUE INDEX uq_incident_open_group ON incidents (tenant_id, group_key) "
        f"WHERE status IN {_OPEN} AND group_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_incident_open_group")
