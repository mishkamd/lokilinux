"""Add a unique constraint on agent_vulnerabilities(agent_id, cve_id, package_name).

Revision ID: 021
Create Date: 2026-07-31

agent_vulnerabilities had no unique constraint at all — every heartbeat that
reports a CVE would need one to ON CONFLICT DO UPDATE against, the same
pattern packages already uses (uq_packages_agent_name_version). Without it,
the only options are duplicate rows per re-report or a SELECT-then-branch
race under concurrent heartbeats; the constraint makes upsert atomic instead.
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_vuln_agent_cve_package",
        "agent_vulnerabilities",
        ["agent_id", "cve_id", "package_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_vuln_agent_cve_package", "agent_vulnerabilities", type_="unique")
