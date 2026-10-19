"""Re-sync compliance_rules.status drift (Enterprise Compliance plan U3 follow-up).

Migration 036 added the column and backfilled it once, but the SQLAlchemy
model never mapped it — so every rule inserted/updated by
curated_rules_loader.py or complianceascode_importer.py between 036 landing
and the model gaining the column kept the column's SQL DEFAULT ('ACTIVE')
instead of the correct value. Re-running 036's exact backfill logic is safe
and idempotent (same WHERE clauses either way) and fixes that drift; the
application-layer fix (both loaders now write status explicitly) prevents
it recurring.

Revision ID: 042
Create Date: 2026-08-27
"""

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE compliance_rules SET status = 'DISABLED' "
        "WHERE is_enabled = false AND status <> 'DISABLED'"
    )
    op.execute(
        "UPDATE compliance_rules SET status = 'REFERENCE_ONLY' "
        "WHERE check_source = 'OVAL_UNMAPPED' AND is_enabled <> false "
        "AND status <> 'REFERENCE_ONLY'"
    )
    op.execute(
        "UPDATE compliance_rules SET status = 'ACTIVE' "
        "WHERE is_enabled = true AND check_source <> 'OVAL_UNMAPPED' AND status <> 'ACTIVE'"
    )


def downgrade() -> None:
    # No-op — this migration only corrects data drift within the existing
    # column's own defined semantics; there is nothing to revert to.
    pass
