"""Add Compliance Policy Engine tables (Compliance module, Phase 2).

Revision ID: 016
Create Date: 2026-07-29

Second slice of the Infrastructure Compliance & Drift Management module
(docs/compliance/). Scope matches the Phase 2 roadmap entry in
docs/compliance/13-OPS.md: rule catalog (imported from ComplianceAsCode),
policy sets/assignments, and per-agent rule evaluation + scoring. Drift
detection and remediation tables land in later migrations as their phases
are built.

rule_evaluations and compliance_scores are TimescaleDB hypertables,
space-partitioned on agent_id (16 partitions), same recipe as
inventory_deltas in 015 and agent_metrics in 001. compliance_scores_daily
is a continuous aggregate powering the dashboard trend charts without
scanning raw rows.

standard_refs (not "references" — reserved word in PostgreSQL, caught by a
dry-run during the architecture-doc verification pass, see
docs/compliance/01-DATA-MODEL.md).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Rule catalog ───────────────────────────────────────────────────────
    op.create_table(
        "compliance_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_key", sa.String(255), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("rationale", sa.Text),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("check_source", sa.String(20), nullable=False, server_default="CEL"),
        sa.Column("check_expr", sa.Text),
        sa.Column("expected_value", postgresql.JSONB),
        sa.Column("platform_filter", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("standard_refs", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remediation_template_id", postgresql.UUID(as_uuid=True)),  # FK added after remediation_templates exists
        sa.Column("source", sa.String(30), nullable=False, server_default="complianceascode"),
        sa.Column("source_version", sa.String(50)),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_compliance_rules_domain", "compliance_rules", ["domain"])
    op.create_index("ix_compliance_rules_severity", "compliance_rules", ["severity"])
    op.create_index("ix_compliance_rules_standard_refs_gin", "compliance_rules", ["standard_refs"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_compliance_rules_search ON compliance_rules USING GIN (title gin_trgm_ops)"
    )

    op.create_table(
        "remediation_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_key", sa.String(255), sa.ForeignKey("compliance_rules.rule_key"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("source", sa.String(30), nullable=False, server_default="complianceascode"),
        sa.Column("git_path", sa.String(500)),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("rule_key", "provider", "version", name="uq_remediation_templates_rule_provider_version"),
    )
    op.create_foreign_key(
        "fk_compliance_rules_remediation", "compliance_rules", "remediation_templates",
        ["remediation_template_id"], ["id"],
    )

    # ── Policy sets ────────────────────────────────────────────────────────
    op.create_table(
        "policy_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("framework", sa.String(30), nullable=False),
        sa.Column("version", sa.String(50)),
        sa.Column("description", sa.Text),
        sa.Column("source_profile", sa.String(255)),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "policy_set_rules",
        sa.Column("policy_set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policy_sets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("compliance_rules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("severity_override", sa.String(20)),
    )

    op.create_table(
        "policy_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("policy_set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policy_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_selector", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_policy_assignments_scope", "policy_assignments", ["scope_type"])
    op.create_index("ix_policy_assignments_selector_gin", "policy_assignments", ["scope_selector"], postgresql_using="gin")

    # ── Evaluation + scoring (hypertables) ────────────────────────────────
    op.create_table(
        "rule_evaluations",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("policy_set_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("actual_value", postgresql.JSONB),
        sa.Column("evidence", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
    )
    op.execute(
        "SELECT create_hypertable('rule_evaluations', 'time', if_not_exists => TRUE, "
        "partitioning_column => 'agent_id', number_partitions => 16)"
    )
    op.create_index("ix_rule_eval_agent_time", "rule_evaluations", ["agent_id", sa.text("time DESC")])
    op.create_index("ix_rule_eval_rule_result", "rule_evaluations", ["rule_id", "result"])
    op.execute(
        "ALTER TABLE rule_evaluations SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id')"
    )
    op.execute("SELECT add_compression_policy('rule_evaluations', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('rule_evaluations', INTERVAL '180 days')")

    op.create_table(
        "compliance_scores",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("category", sa.String(30), nullable=False, primary_key=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("passed_count", sa.Integer, nullable=False),
        sa.Column("failed_count", sa.Integer, nullable=False),
        sa.Column("not_applicable_count", sa.Integer, nullable=False),
    )
    op.execute(
        "SELECT create_hypertable('compliance_scores', 'time', if_not_exists => TRUE, "
        "partitioning_column => 'agent_id', number_partitions => 16)"
    )
    op.execute(
        "ALTER TABLE compliance_scores SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id')"
    )
    op.execute("SELECT add_compression_policy('compliance_scores', INTERVAL '30 days')")
    op.execute("SELECT add_retention_policy('compliance_scores', INTERVAL '2 years')")

    op.execute(
        """
        CREATE MATERIALIZED VIEW compliance_scores_daily
        WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 day', time) AS day,
               agent_id, category,
               avg(score) AS avg_score,
               min(score) AS min_score
        FROM compliance_scores
        GROUP BY day, agent_id, category
        WITH NO DATA
        """
    )
    op.execute(
        "SELECT add_continuous_aggregate_policy('compliance_scores_daily', "
        "start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour', "
        "schedule_interval => INTERVAL '1 hour')"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS compliance_scores_daily CASCADE")

    op.execute("SELECT remove_retention_policy('compliance_scores', if_exists => TRUE)")
    op.execute("SELECT remove_compression_policy('compliance_scores', if_exists => TRUE)")
    op.drop_table("compliance_scores")

    op.execute("SELECT remove_retention_policy('rule_evaluations', if_exists => TRUE)")
    op.execute("SELECT remove_compression_policy('rule_evaluations', if_exists => TRUE)")
    op.drop_index("ix_rule_eval_rule_result", table_name="rule_evaluations")
    op.drop_index("ix_rule_eval_agent_time", table_name="rule_evaluations")
    op.drop_table("rule_evaluations")

    op.drop_index("ix_policy_assignments_selector_gin", table_name="policy_assignments")
    op.drop_index("ix_policy_assignments_scope", table_name="policy_assignments")
    op.drop_table("policy_assignments")
    op.drop_table("policy_set_rules")
    op.drop_table("policy_sets")

    op.drop_constraint("fk_compliance_rules_remediation", "compliance_rules", type_="foreignkey")
    op.drop_table("remediation_templates")

    op.drop_index("ix_compliance_rules_search", table_name="compliance_rules")
    op.drop_index("ix_compliance_rules_standard_refs_gin", table_name="compliance_rules")
    op.drop_index("ix_compliance_rules_severity", table_name="compliance_rules")
    op.drop_index("ix_compliance_rules_domain", table_name="compliance_rules")
    op.drop_table("compliance_rules")
