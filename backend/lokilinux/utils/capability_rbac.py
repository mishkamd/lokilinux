"""Capability-based RBAC for privileged job creation (plan §26).

Maps each execution capability to the platform roles allowed to request it.
Roles are the existing enum (VIEWER/MANAGER/OPERATOR/ADMIN/AUDITOR) — the
finer-grained Security/Automation Operator split needs an alembic enum
extension and lands with that migration; until then ADMIN covers both.

Derivation mirrors agent/internal/security/capabilities.go: a job_type maps
to its capability; WORKFLOW_STEPS expands per step type present.
"""

from typing import Any, Iterable, Optional

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


def required_capabilities(job_type: str, params: Optional[dict] = None) -> set[str]:
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
    if cap:
        return {cap}
    # Fail closed. An unmapped job_type must not be creatable by everyone:
    # the agent dispatches any job type it does not know through its generic
    # branch, which runs params["command"] as root — so "unknown" is at least
    # as dangerous as CUSTOM_COMMAND. EXEC_BASH (ADMIN-only) is the strictest
    # gate we have; a new job type must be mapped explicitly to get a weaker one.
    return {"EXEC_BASH"}


def unauthorized_capabilities(role: str, capabilities: Iterable[str]) -> list[str]:
    """Capabilities `role` may NOT request. Unknown roles are denied everything."""
    allowed = CAPABILITY_MIN_ROLES  # name → role set
    denied = []
    for cap in capabilities:
        roles = allowed.get(cap)
        if roles is None or role not in roles:
            denied.append(cap)
    return sorted(denied)


def assert_can_create(role: str, job_type: str, params: Optional[dict] = None) -> None:
    """Raises PermissionError listing denied capabilities, if any."""
    denied = unauthorized_capabilities(role or "", required_capabilities(job_type, params))
    if denied:
        raise PermissionError(
            f"role {role!r} lacks capabilities required to create this job: {', '.join(denied)}"
        )


def agent_can_run_job_type(capabilities: Optional[Iterable[str]], job_type: str) -> bool:
    """Whether an agent that reports `capabilities` can run `job_type`.

    The heartbeat list is ADVISORY. An agent that reports nothing is an agent
    that predates the field: its abilities are unknown, not empty — so an
    empty list must not block the job. Only a report that exists and lacks
    the job type is a "no".
    """
    reported = list(capabilities or [])
    if not reported:
        return True
    return job_type in reported


# Job types whose agent-side execution IS the bare `command` parameter. The
# agent runs params["command"] as root for any job type it does not dispatch
# to a dedicated handler (agent/internal/agent/manager.go), so a `command` key
# on any other job type is an attempt to smuggle a shell line past the
# EXEC_BASH gate.
_COMMAND_PARAM_JOB_TYPES = frozenset({"CUSTOM_COMMAND"})


def assert_no_smuggled_command(job_type: str, params: Optional[dict[str, Any]] = None) -> None:
    """Reject a top-level `command` parameter on a job type that is not a
    shell job. Raises PermissionError.

    Call this wherever a job is created, not only in the router — policies,
    workflows and services all reach JobService.create_job directly.
    """
    if params and "command" in params and job_type not in _COMMAND_PARAM_JOB_TYPES:
        raise PermissionError(f"job_type {job_type!r} may not carry a 'command' parameter")
