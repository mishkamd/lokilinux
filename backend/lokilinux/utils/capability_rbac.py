"""Capability-based RBAC for privileged job creation (plan §26).

Maps each execution capability to the platform roles allowed to request it.
Roles are the existing enum (VIEWER/MANAGER/OPERATOR/ADMIN/AUDITOR) — the
finer-grained Security/Automation Operator split needs an alembic enum
extension and lands with that migration; until then ADMIN covers both.

Derivation mirrors agent/internal/security/capabilities.go: a job_type maps
to its capability; WORKFLOW_STEPS expands per step type present.
"""

from typing import Iterable

ALL_ROLES = frozenset({"VIEWER", "MANAGER", "OPERATOR", "ADMIN", "AUDITOR"})

# capability -> roles allowed to create jobs demanding it
CAPABILITY_MIN_ROLES = {
    "READ_SYSTEM": ALL_ROLES,
    "READ_LOGS": ALL_ROLES,
    "SERVICE_CONTROL": frozenset({"OPERATOR", "MANAGER", "ADMIN"}),
    "PACKAGE_MANAGEMENT": frozenset({"OPERATOR", "MANAGER", "ADMIN"}),
    "FILE_WRITE": frozenset({"OPERATOR", "MANAGER", "ADMIN"}),
    "SECURITY_REMEDIATION": frozenset({"MANAGER", "ADMIN"}),
    "REBOOT_HOST": frozenset({"MANAGER", "ADMIN"}),
    "FIREWALL_CONFIGURATION": frozenset({"MANAGER", "ADMIN"}),
    "EXEC_BASH": frozenset({"ADMIN"}),
    "EXEC_PYTHON": frozenset({"ADMIN"}),
    "EXEC_ANSIBLE": frozenset({"ADMIN"}),
    "PLUGIN_INSTALL": frozenset({"ADMIN"}),
}

_JOB_TYPE_CAPABILITY = {
    "HEARTBEAT": "READ_SYSTEM",
    "FILE_READ": "READ_SYSTEM",
    "LOG_READ": "READ_LOGS",
    "INVENTORY_SCAN": "READ_SYSTEM",
    "CVE_SCAN": "READ_SYSTEM",
    "SERVICE": "SERVICE_CONTROL",
    "FILE": "FILE_WRITE",
    "PACKAGE_UPDATE": "PACKAGE_MANAGEMENT",
    "SECURITY_PATCH": "PACKAGE_MANAGEMENT",
    "COMPLIANCE_REMEDIATE": "SECURITY_REMEDIATION",
    "REMEDIATION": "SECURITY_REMEDIATION",
    "REBOOT": "REBOOT_HOST",
    "FIREWALL_CHANGE": "FIREWALL_CONFIGURATION",
    "CUSTOM_COMMAND": "EXEC_BASH",
    "WORKFLOW_STEPS": "EXEC_BASH",
    "ANSIBLE_PLAYBOOK": "EXEC_ANSIBLE",
    "PLUGIN_INSTALL": "PLUGIN_INSTALL",
}

_STEP_TYPE_TO_CAPABILITY = {
    "command": "EXEC_BASH",
    "package": "PACKAGE_MANAGEMENT",
    "service": "SERVICE_CONTROL",
    "system": "REBOOT_HOST",
    "file": "FILE_WRITE",
    "ansible": "EXEC_ANSIBLE",
}


def required_capabilities(job_type: str, params: dict | None = None) -> set[str]:
    """Capabilities a job demands. WORKFLOW_STEPS expands to the union of its
    steps; unknown step types demand EXEC_BASH (strictest match)."""
    params = params or {}
    if job_type == "WORKFLOW_STEPS":
        caps = {"EXEC_BASH"}
        for step in params.get("steps") or []:
            st = step.get("type") if isinstance(step, dict) else None
            cap = _STEP_TYPE_TO_CAPABILITY.get(st or "")
            if cap:
                caps.add(cap)
        return caps
    cap = _JOB_TYPE_CAPABILITY.get(job_type)
    return {cap} if cap else set()


def unauthorized_capabilities(role: str, capabilities: Iterable[str]) -> list[str]:
    """Capabilities `role` may NOT request. Unknown roles are denied everything."""
    allowed = CAPABILITY_MIN_ROLES  # name → role set
    denied = []
    for cap in capabilities:
        roles = allowed.get(cap)
        if roles is None or role not in roles:
            denied.append(cap)
    return sorted(denied)


def assert_can_create(role: str, job_type: str, params: dict | None = None) -> None:
    """Raises PermissionError listing denied capabilities, if any."""
    denied = unauthorized_capabilities(role or "", required_capabilities(job_type, params))
    if denied:
        raise PermissionError(
            f"role {role!r} lacks capabilities required to create this job: {', '.join(denied)}"
        )
