"""compliance_rules.status — explicit rule lifecycle (Enterprise Compliance plan U3 / KTD2).

States: ACTIVE | DISABLED | REFERENCE_ONLY | DEPRECATED.
Backfill derives from existing columns:
  is_enabled = false            -> DISABLED      (admin-disabled, precedence first)
  check_source = 'OVAL_UNMAPPED' -> REFERENCE_ONLY (imported reference content,
                                                   never executable — docs/compliance
                                                   §7 importer quarantine)
  everything else               -> ACTIVE        (default)
Only ACTIVE rules reach the CEL evaluator (services/compliance storage loaders
filter on this); REFERENCE_ONLY never contributes to scores, findings, or
coverage numerators.

Revision ID: 036
Create Date: 2026-08-26
"""

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE compliance_rules ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'")
    # Precedence per KTD2: DISABLED wins over REFERENCE_ONLY.
    op.execute("UPDATE compliance_rules SET status = 'DISABLED' WHERE is_enabled = false")
    op.execute(
        "UPDATE compliance_rules SET status = 'REFERENCE_ONLY' "
        "WHERE check_source = 'OVAL_UNMAPPED' AND is_enabled <> false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_rules_active ON compliance_rules (id) WHERE status = 'ACTIVE'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_compliance_rules_active")
    op.execute("ALTER TABLE compliance_rules DROP COLUMN IF EXISTS status")
