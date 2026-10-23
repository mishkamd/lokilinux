"""
The canonical compliance domain vocabulary.

A fact's domain is decided by the agent's collector
(agent/internal/compliance/*_collector.go) — 24 of them. The backend needs
the same list to (a) offer real filter values instead of a free-text box
and (b) group domains into report categories. Keeping both in one module
stops the two from drifting: a domain with no category used to land
silently in "configuration" (report_service's `.get(domain, "configuration")`).

ponytail: hardcoded list, mirrored from the agent's collectors — 24 entries
that change only when a collector is added or removed. The agent asserts
its own registry is unique (agent/internal/compliance/collector_test.go);
this list has to be kept in step by hand. Upgrade path when it starts to
churn: expose the agent's registry over the heartbeat and cache it, so
the vocabulary comes from the fleet instead of from a constant.
"""

COMPLIANCE_DOMAINS: tuple[str, ...] = (
    "auditd",
    "capabilities",
    "certificates",
    "container_runtime",
    "cron",
    "file_integrity",
    "firewall",
    "kernel",
    "kernel_modules",
    "login_defs",
    "mounts",
    "network",
    "open_ports",
    "pam",
    "password_policy",
    "processes",
    "repositories",
    "selinux",
    "sshd",
    "sudo",
    "sysctl",
    "systemd_services",
    "time_sync",
    "users",
)

# Domain -> report category. The 18 original mappings are unchanged; the
# other 6 were previously unmapped and fell into "configuration".
CATEGORY_BY_DOMAIN: dict[str, str] = {
    "sshd": "security",
    "pam": "security",
    "auditd": "security",
    "sudo": "security",
    "selinux": "security",
    "firewall": "security",
    "password_policy": "security",
    "login_defs": "configuration",
    "certificates": "security",
    "sysctl": "configuration",
    "systemd_services": "configuration",
    "cron": "configuration",
    "network": "configuration",
    "time_sync": "configuration",
    "capabilities": "configuration",
    "processes": "configuration",
    "open_ports": "configuration",
    "container_runtime": "configuration",
    "mounts": "filesystem",
    "file_integrity": "filesystem",
    "repositories": "filesystem",
    "kernel": "kernel",
    "kernel_modules": "kernel",
}
