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
