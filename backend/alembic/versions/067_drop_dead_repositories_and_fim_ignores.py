"""drop two dead tables with no model, no code and 0 rows (MIS-169).

repositories: left over from the update-management feature (migration 002); the
settings schema already states the table does not exist, and nothing reads it.
file_integrity_ignores (migration 017): superseded by fim_scopes (migration 044).
Live check: 0 rows, no inbound foreign keys.

Revision ID: 067
Create Date: 2026-10-27
"""

from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("repositories")
    op.drop_table("file_integrity_ignores")


def downgrade() -> None:
    # Empty tables with no readers: restore the shape from migrations 002 and 017 if ever needed.
    raise NotImplementedError("dead tables (0 rows); recreate from migrations 002 and 017")
