"""compliance_scores weighted scoring — Enterprise Compliance plan U5 / KTD4 (additive).

New nullable columns alongside the legacy `score` (which keeps being written
unchanged this release):
  weighted_score     NUMERIC(5,2)  severity-weighted pass ratio,
                                   100 x sum(w_i * passed_i) / sum(w_i * applicable_i),
                                   weights CRITICAL=10 HIGH=5 MEDIUM=2 LOW=1;
                                   applicable excludes UNKNOWN and NOT_APPLICABLE
  severity_breakdown JSONB          {"CRITICAL": {"passed": n, "failed": m}, ...}
  unknown_count      INTEGER       evaluations whose required evidence was not
                                   collected (UNKNOWN) — excluded from
                                   denominators but never hidden

Revision ID: 037
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("compliance_scores", sa.Column("weighted_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("compliance_scores", sa.Column("severity_breakdown", postgresql.JSONB, nullable=True))
    op.add_column("compliance_scores", sa.Column("unknown_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("compliance_scores", "unknown_count")
    op.drop_column("compliance_scores", "severity_breakdown")
    op.drop_column("compliance_scores", "weighted_score")
