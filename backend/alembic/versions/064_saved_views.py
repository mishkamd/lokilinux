"""saved_views: named filter views per user (MIS-191).

A saved view stores a name + the list URL it points at. The filter state
itself stays in the URL — this table only makes views listable across devices.

user_id is the raw Better Auth id (a nanoid), stored as text: the auth ids do
not parse as UUIDs.

Revision ID: 064
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("query", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_views_user_scope", "saved_views", ["user_id", "scope"])


def downgrade() -> None:
    op.drop_index("ix_saved_views_user_scope", table_name="saved_views")
    op.drop_table("saved_views")
