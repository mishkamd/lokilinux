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
COMPLIANCE_SNAPSHOT_DOMAIN = "lokilinux.compliance.snapshot"  # + ".{domain}" subject suffix per publish

# Compliance module — baseline invalidation (published by BaselineService,
# consumed by the lokilinux-compliance Go service, docs/compliance/06-BASELINE.md)
COMPLIANCE_BASELINE_PUBLISHED = "lokilinux.compliance.baseline.published"

# Observability pipeline (Observation -> Event -> Signal -> Correlation -> Incident)
EVENT_RAW = "lokilinux.events.raw"            # + ".{source}" subject suffix per publish
EVENT_NORMALIZED = "lokilinux.events.normalized"
SIGNAL_DETECTED = "lokilinux.signals.detected"
SIGNAL_RESOLVED = "lokilinux.signals.resolved"
INCIDENT_CREATED = "lokilinux.incidents.created"
INCIDENT_UPDATED = "lokilinux.incidents.updated"
INCIDENT_RESOLVED = "lokilinux.incidents.resolved"
