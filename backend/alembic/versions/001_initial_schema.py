"""Initial schema — all core tables.

Revision ID: 001
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── policies (no FK deps — created first so agents can reference it) ──────
    op.create_table(
        "policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("policy_type", sa.String(50)),
        sa.Column("rules", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("target_servers", postgresql.JSONB),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parent_policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policies.id")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_policies_policy_type", "policies", ["policy_type"])
    op.create_index("ix_policies_is_enabled", "policies", ["is_enabled"])
    op.create_index("ix_policies_priority", "policies", ["priority"])

    # ── agents ────────────────────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.Enum("PENDING","REGISTERED","ACTIVE","INACTIVE","UNHEALTHY","MAINTENANCE", name="agentstatus"), nullable=False, server_default="PENDING"),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True)),
        sa.Column("last_heartbeat_ip", sa.String(45)),
        sa.Column("cert_fingerprint", sa.String(64), unique=True),
        sa.Column("cert_valid_from", sa.DateTime(timezone=True)),
        sa.Column("cert_valid_until", sa.DateTime(timezone=True)),
        sa.Column("agent_version", sa.String(50)),
        sa.Column("platform_version", sa.String(50)),
        sa.Column("hostname", sa.String(255)),
        sa.Column("os_family", sa.String(50)),
        sa.Column("os_distro", sa.String(100)),
        sa.Column("os_version", sa.String(50)),
        sa.Column("kernel_version", sa.String(100)),
        sa.Column("arch", sa.String(50)),
        sa.Column("scope", sa.String(50), nullable=False, server_default="default"),
        sa.Column("current_policy_id", postgresql.UUID(as_uuid=True)),  # FK added via ALTER below
        sa.Column("plugin_policy_id", postgresql.UUID(as_uuid=True)),   # FK added via ALTER below
        sa.Column("tags", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("custom_facts", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cve_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updates_available", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agents_status", "agents", ["status"])
    op.create_index("ix_agents_scope", "agents", ["scope"])
    op.create_index("ix_agents_hostname", "agents", ["hostname"])
    op.create_index("ix_agents_os_distro", "agents", ["os_distro"])
    op.create_index("ix_agents_last_heartbeat", "agents", ["last_heartbeat"])

    # Deferred FK from agents → policies (avoids dependency issues in other DBs)
    op.create_foreign_key("fk_agent_current_policy", "agents", "policies", ["current_policy_id"], ["id"])
    op.create_foreign_key("fk_agent_plugin_policy", "agents", "policies", ["plugin_policy_id"], ["id"])

    # ── packages ──────────────────────────────────────────────────────────────
    op.create_table(
        "packages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("architecture", sa.String(50)),
        sa.Column("repository", sa.String(255)),
        sa.Column("source_type", sa.String(50)),
        sa.Column("is_update_available", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_security_update_available", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("latest_version", sa.String(100)),
        sa.Column("installed_at", sa.DateTime(timezone=True)),
        sa.Column("last_update_check", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_id", "name", "version", name="uq_packages_agent_name_version"),
    )
    op.create_index("ix_packages_agent_id", "packages", ["agent_id"])
    op.create_index("ix_packages_is_update_available", "packages", ["is_update_available"])
    op.create_index("ix_packages_is_security_update_available", "packages", ["is_security_update_available"])

    # ── cves ─────────────────────────────────────────────────────────────────
    op.create_table(
        "cves",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("cve_id", sa.String(50), unique=True, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("cvss_v3_score", sa.Float),
        sa.Column("cvss_v3_severity", sa.String(20)),
        sa.Column("published_date", sa.Date),
        sa.Column("updated_date", sa.Date),
        sa.Column("nvd_url", sa.String(255)),
        sa.Column("debian_url", sa.String(255)),
        sa.Column("ubuntu_url", sa.String(255)),
        sa.Column("redhat_url", sa.String(255)),
        sa.Column("cwe_ids", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("affected_packages", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_zero_day", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_actively_exploited", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_cves_cve_id", "cves", ["cve_id"])
    op.create_index("ix_cves_cvss_v3_score", "cves", ["cvss_v3_score"])
    op.create_index("ix_cves_cvss_v3_severity", "cves", ["cvss_v3_severity"])
    op.create_index("ix_cves_published_date", "cves", ["published_date"])
    op.create_index("ix_cves_is_actively_exploited", "cves", ["is_actively_exploited"])
    # Full-text search index
    op.execute(
        "CREATE INDEX ix_cves_fulltext ON cves "
        "USING GIN(to_tsvector('english', COALESCE(title,'') || ' ' || COALESCE(description,'')))"
    )

    # ── package_vulnerabilities ───────────────────────────────────────────────
    op.create_table(
        "package_vulnerabilities",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("cve_id", sa.String(50), sa.ForeignKey("cves.cve_id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_name", sa.String(255), nullable=False),
        sa.Column("distro", sa.String(100), nullable=False),
        sa.Column("affected_versions", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fixed_version", sa.String(100)),
        sa.Column("is_fixed_available", sa.Boolean),
        sa.Column("fix_available_date", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("cve_id", "package_name", "distro", name="uq_pkg_vuln_cve_pkg_distro"),
    )
    op.create_index("ix_pkg_vuln_cve_id", "package_vulnerabilities", ["cve_id"])
    op.create_index("ix_pkg_vuln_package_name", "package_vulnerabilities", ["package_name"])

    # ── jobs (depends on policies; no single agent_id — target_servers is JSONB) ──
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("target_servers", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("total_servers", sa.Integer),
        sa.Column("parameters", postgresql.JSONB),
        sa.Column("status", sa.Enum("QUEUED","SCHEDULED","PENDING","RUNNING","COMPLETED","FAILED","TIMEOUT","CANCELLED", name="jobstatus"), nullable=False, server_default="QUEUED"),
        sa.Column("scheduled_time", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policies.id")),
        sa.Column("requires_approval", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("dedup_key", sa.String(64)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_job_type", "jobs", ["job_type"])
    op.create_index("ix_jobs_scheduled_time", "jobs", ["scheduled_time"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    # Partial unique index: dedup_key only where NOT NULL
    op.create_index(
        "uq_jobs_dedup_key", "jobs", ["dedup_key"],
        unique=True, postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )

    # ── job_results ───────────────────────────────────────────────────────────
    op.create_table(
        "job_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("exit_code", sa.Integer),
        sa.Column("error_message", sa.Text),
        sa.Column("stdout", sa.Text),
        sa.Column("stderr", sa.Text),
        sa.Column("duration_seconds", sa.Integer),
        sa.Column("resources_used", postgresql.JSONB),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_job_results_job_id", "job_results", ["job_id"])
    op.create_index("ix_job_results_agent_id", "job_results", ["agent_id"])
    op.create_index("ix_job_results_status", "job_results", ["status"])

    # ── agent_vulnerabilities (depends on agents, cves, jobs) ─────────────────
    op.create_table(
        "agent_vulnerabilities",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cve_id", sa.String(50), sa.ForeignKey("cves.cve_id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_name", sa.String(255), nullable=False),
        sa.Column("package_version", sa.String(100), nullable=False),
        sa.Column("cvss_score", sa.Float),
        sa.Column("severity", sa.String(20)),
        sa.Column("risk_score", sa.Float),
        sa.Column("fix_available", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("recommended_action", sa.String(50)),
        sa.Column("is_remediated", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("remediation_date", sa.DateTime(timezone=True)),
        sa.Column("remediation_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id")),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_check", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_vuln_agent_id", "agent_vulnerabilities", ["agent_id"])
    op.create_index("ix_agent_vuln_cve_id", "agent_vulnerabilities", ["cve_id"])
    op.create_index("ix_agent_vuln_severity", "agent_vulnerabilities", ["severity"])
    op.create_index("ix_agent_vuln_is_remediated", "agent_vulnerabilities", ["is_remediated"])
    op.create_index("ix_agent_vuln_risk_score", "agent_vulnerabilities", ["risk_score"])

    # ── plugins ───────────────────────────────────────────────────────────────
    op.create_table(
        "plugins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("author", sa.String(255)),
        sa.Column("icon_url", sa.String(512)),
        sa.Column("documentation_url", sa.String(512)),
        sa.Column("plugin_type", sa.String(50), nullable=False),
        sa.Column("min_platform_version", sa.String(50)),
        sa.Column("max_platform_version", sa.String(50)),
        sa.Column("source_url", sa.String(512)),
        sa.Column("manifest", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("checksum", sa.String(64)),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_installed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("installation_status", sa.Enum("PENDING_INSTALL","INSTALLING","INSTALLED","INSTALLING_FAILED","ENABLED","DISABLED","ERROR", name="pluginstatus"), nullable=False, server_default="PENDING_INSTALL"),
        sa.Column("configuration", postgresql.JSONB),
        sa.Column("config_schema", postgresql.JSONB),
        sa.Column("required_permissions", postgresql.JSONB),
        sa.Column("is_latest", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("security_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("download_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rating", sa.Float, nullable=False, server_default="0"),
        sa.Column("installed_at", sa.DateTime(timezone=True)),
        sa.Column("last_enabled_at", sa.DateTime(timezone=True)),
        sa.Column("last_disabled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_plugins_plugin_type", "plugins", ["plugin_type"])
    op.create_index("ix_plugins_is_installed", "plugins", ["is_installed"])
    op.create_index("ix_plugins_is_enabled", "plugins", ["is_enabled"])

    # ── plugin_installations ──────────────────────────────────────────────────
    op.create_table(
        "plugin_installations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("plugin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE")),
        sa.Column("status", sa.String(50)),
        sa.Column("error_message", sa.Text),
        sa.Column("local_config", postgresql.JSONB),
        sa.Column("installed_version", sa.String(50)),
        sa.Column("installed_at", sa.DateTime(timezone=True)),
        sa.Column("enabled_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_plugin_inst_plugin_id", "plugin_installations", ["plugin_id"])
    op.create_index("ix_plugin_inst_agent_id", "plugin_installations", ["agent_id"])
    op.create_index("ix_plugin_inst_status", "plugin_installations", ["status"])

    # ── alert_rules (self-ref FK) ─────────────────────────────────────────────
    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("conditions", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("alert_severity", sa.String(50)),
        sa.Column("notification_channels", postgresql.JSONB),
        sa.Column("escalation_policy", postgresql.UUID(as_uuid=True), sa.ForeignKey("alert_rules.id")),
        sa.Column("escalation_delay_minutes", sa.Integer),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_alert_rules_is_enabled", "alert_rules", ["is_enabled"])

    # ── alerts ────────────────────────────────────────────────────────────────
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(50)),
        sa.Column("alert_type", sa.String(100)),
        sa.Column("description", sa.Text),
        sa.Column("context_data", postgresql.JSONB),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("cve_id", sa.String(50), sa.ForeignKey("cves.cve_id", ondelete="SET NULL")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policies.id", ondelete="SET NULL")),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("alert_rules.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("notification_channels", postgresql.JSONB),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("escalation_level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("escalated_at", sa.DateTime(timezone=True)),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_alerts_severity", "alerts", ["severity"])
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_agent_id", "alerts", ["agent_id"])
    op.create_index("ix_alerts_cve_id", "alerts", ["cve_id"])
    op.create_index("ix_alerts_triggered_at", "alerts", ["triggered_at"])

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(255)),
        sa.Column("actor_type", sa.String(50)),
        sa.Column("actor_name", sa.String(255)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100)),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("changes", postgresql.JSONB),
        sa.Column("status", sa.String(50)),
        sa.Column("error_message", sa.Text),
        sa.Column("source_ip", sa.String(45)),
        sa.Column("user_agent", sa.Text),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.execute(
        "CREATE INDEX ix_audit_logs_fulltext ON audit_logs "
        "USING GIN(to_tsvector('english', COALESCE(action,'') || ' ' || COALESCE(resource_type,'')))"
    )

    # ── policy_audit ──────────────────────────────────────────────────────────
    op.create_table(
        "policy_audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("change_type", sa.String(50), nullable=False),
        sa.Column("old_value", postgresql.JSONB),
        sa.Column("new_value", postgresql.JSONB),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_policy_audit_policy_id", "policy_audit", ["policy_id"])
    op.create_index("ix_policy_audit_changed_at", "policy_audit", ["changed_at"])

    # ── user_profiles ─────────────────────────────────────────────────────────
    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ba_user_id", sa.String(255), unique=True, nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("avatar_url", sa.String(500)),
        sa.Column("preferences", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── role_assignments ──────────────────────────────────────────────────────
    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ba_user_id", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("ADMIN","MANAGER","OPERATOR","VIEWER","AUDITOR", name="userrole"), nullable=False),
        sa.Column("scope_type", sa.String(50), nullable=False, server_default="global"),
        sa.Column("scope_id", sa.String(255)),
        sa.Column("assigned_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_role_assignments_ba_user_id", "role_assignments", ["ba_user_id"])

    # ── agent_health ──────────────────────────────────────────────────────────
    op.create_table(
        "agent_health",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cpu_usage", sa.Float),
        sa.Column("memory_usage", sa.Float),
        sa.Column("disk_usage", sa.Float),
        sa.Column("network_latency_ms", sa.Float),
        sa.Column("is_disk_full", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_memory_critical", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("connection_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_health_agent_id", "agent_health", ["agent_id"])
    op.create_index("ix_agent_health_recorded_at", "agent_health", ["recorded_at"])

    # ── agent_metrics (TimescaleDB hypertable) ────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.create_table(
        "agent_metrics",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("cpu_user", sa.Float),
        sa.Column("cpu_system", sa.Float),
        sa.Column("cpu_idle", sa.Float),
        sa.Column("cpu_count", sa.Integer),
        sa.Column("memory_total", sa.BigInteger),
        sa.Column("memory_used", sa.BigInteger),
        sa.Column("memory_available", sa.BigInteger),
        sa.Column("disk_total", sa.BigInteger),
        sa.Column("disk_used", sa.BigInteger),
        sa.Column("disk_io_read_bytes", sa.BigInteger),
        sa.Column("disk_io_write_bytes", sa.BigInteger),
        sa.Column("network_bytes_in", sa.BigInteger),
        sa.Column("network_bytes_out", sa.BigInteger),
        sa.Column("network_packets_in", sa.BigInteger),
        sa.Column("network_packets_out", sa.BigInteger),
        sa.Column("process_count", sa.Integer),
        sa.Column("thread_count", sa.Integer),
        sa.Column("tags", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.execute("SELECT create_hypertable('agent_metrics', 'time', if_not_exists => TRUE)")
    op.create_index("ix_agent_metrics_agent_id_time", "agent_metrics", ["agent_id", sa.text("time DESC")])
    # TimescaleDB compression (activates after 30 days)
    op.execute(
        "ALTER TABLE agent_metrics SET ("
        "timescaledb.compress, timescaledb.compress_segmentby = 'agent_id')"
    )
    op.execute("SELECT add_compression_policy('agent_metrics', INTERVAL '30 days')")

    # ── settings ──────────────────────────────────────────────────────────────
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(255), unique=True, nullable=False),
        sa.Column("value", sa.Text),
        sa.Column("value_type", sa.String(50)),
        sa.Column("description", sa.Text),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_mutable", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_settings_key", "settings", ["key"])

def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("settings")
    op.drop_table("agent_metrics")
    op.drop_table("agent_health")
    op.drop_table("role_assignments")
    op.drop_table("user_profiles")
    op.drop_table("policy_audit")
    op.drop_table("audit_logs")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
    op.drop_table("plugin_installations")
    op.drop_table("plugins")
    op.drop_table("agent_vulnerabilities")
    op.drop_table("job_results")
    op.drop_table("jobs")
    op.drop_table("package_vulnerabilities")
    op.drop_table("cves")
    op.drop_table("packages")
    op.drop_constraint("fk_agent_current_policy", "agents", type_="foreignkey")
    op.drop_constraint("fk_agent_plugin_policy", "agents", type_="foreignkey")
    op.drop_table("agents")
    op.drop_table("policies")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS userrole")
    op.execute("DROP TYPE IF EXISTS pluginstatus")
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS agentstatus")
