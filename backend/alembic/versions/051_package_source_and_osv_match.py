"""packages.source_package — source name for Debian/Ubuntu CVE matching (ROADMAP R4).

Agents report the source package of each binary (dpkg-query ${source:Package}).
OSV indexes Debian and Ubuntu advisories by source name, so libssl3 has to be
looked up as openssl. Nullable with no backfill: rows written before the agent
change have no source and fall back to the binary name.

Revision ID: 051
Create Date: 2026-10-14
"""

import sqlalchemy as sa

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("packages", sa.Column("source_package", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("packages", "source_package")
