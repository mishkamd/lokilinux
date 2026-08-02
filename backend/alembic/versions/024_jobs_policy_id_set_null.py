"""Fix jobs.policy_id FK to ON DELETE SET NULL.

Deleting a policy with any job history crashed with a raw IntegrityError
(FK default is RESTRICT) — caught live: jobs.policy_id was write-only until
Phase 1's policy engine started reading/populating it. alerts.policy_id
already uses ondelete="SET NULL" for the same "keep the row, detach the
reference" reasoning; jobs.policy_id was the one outlier.

Revision ID: 024
Revises: 023
"""

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("jobs_policy_id_fkey", "jobs", type_="foreignkey")
    op.create_foreign_key(
        "jobs_policy_id_fkey", "jobs", "policies", ["policy_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("jobs_policy_id_fkey", "jobs", type_="foreignkey")
    op.create_foreign_key("jobs_policy_id_fkey", "jobs", "policies", ["policy_id"], ["id"])
