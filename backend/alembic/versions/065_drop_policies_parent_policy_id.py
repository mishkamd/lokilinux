"""drop policies.parent_policy_id — a column nothing ever wrote or read.

The legacy `policies` table (the Enforcement product) declared a
self-referencing parent_policy_id, implying a policy hierarchy. Nothing
in backend/, frontend/, the Go services or the agent ever set or query
it: grep found exactly two hits, both of them the column's own
declaration (models/policy.py and the initial migration).

A dead self-FK is worse than a missing one — it advertises an inheritance
model the product does not have, and every reader of the schema has to
work out that nobody uses it. The live replacement for "a policy built on
top of another" is policy_sets' parent_policy_set_id, which IS used.

Revision ID: 065
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("policies", "parent_policy_id")


def downgrade() -> None:
    op.add_column(
        "policies",
        sa.Column(
            "parent_policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policies.id"),
            nullable=True,
        ),
    )
