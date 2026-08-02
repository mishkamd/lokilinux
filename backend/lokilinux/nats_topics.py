"""
LokiLinux — NATS topic names (single source of truth).

All topics use the `lokilinux.` prefix (see CLAUDE.md "Event Bus"). Import these
constants instead of writing raw strings so a typo fails at import, not silently
at runtime with a subscription that never fires.
"""

# Jobs
JOB_CREATED = "lokilinux.job.created"
JOB_RESULT = "lokilinux.job.result"

# Policies
POLICY_CHANGED = "lokilinux.policy.changed"
POLICY_APPLY = "lokilinux.policy.apply"

# Alerts / agent health
ALERT_CREATED = "lokilinux.alert.created"
AGENT_UNHEALTHY = "lokilinux.agent.unhealthy"

# CVE feed
CVE_DATABASE_UPDATED = "lokilinux.cve.database.updated"

# Plugins
PLUGIN_INSTALL = "lokilinux.plugin.install"
PLUGIN_UNINSTALL = "lokilinux.plugin.uninstall"

# Compliance module — snapshot ingest (published by the gRPC servicer passthrough,
# consumed by the lokilinux-compliance Go service, docs/compliance/04-PROTOCOL.md)
COMPLIANCE_HASHES_REPORTED = "lokilinux.compliance.hashes.reported"
COMPLIANCE_SNAPSHOT_DOMAIN = "lokilinux.compliance.snapshot"  # + ".{domain}" subject suffix per publish

# Compliance module — results (published by lokilinux-compliance, consumed by
# lokilinux-api NATS workers for WebSocket push / cache invalidation)
COMPLIANCE_DRIFT_DETECTED = "lokilinux.compliance.drift.detected"
COMPLIANCE_SCORE_UPDATED = "lokilinux.compliance.score.updated"
COMPLIANCE_BASELINE_PUBLISHED = "lokilinux.compliance.baseline.published"
