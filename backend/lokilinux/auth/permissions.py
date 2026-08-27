"""
LokiLinux — Granular compliance permissions registry (Enterprise Compliance
plan U9/KTD5).

Table-driven mapping: each permission names one sensitive action; its value
is the set of roles allowed to perform it (besides ADMIN, which
require_permission() always lets through — same "ADMIN always passes"
contract as require_role()). A single source of truth instead of
require_role(...) role-lists scattered per route.

Role sets below preserve EXACTLY what require_role(...) already granted on
each route before this migration (verified route-by-route against
routers/compliance/{exceptions,remediation,policy_engine}.py) — this
registry renames/documents existing access, it does not change it.
Tightening (e.g. giving MANAGER exception-approval per the product brief's
intended role model — KTD5: "MANAGER approvals+manage") is a deliberate
follow-up, not bundled here, since it would be a real behavior change
requiring its own sign-off.

Read routes (GET) are deliberately not in this registry yet — plan U9 Task 3
stages adoption write-routes-first, reads later ("findings.view etc.
defaulting any-authenticated until roles tightened").
"""

PERMISSIONS: dict[str, frozenset[str]] = {
    # Exceptions — routers/compliance/exceptions.py
    "compliance.exceptions.create": frozenset({"OPERATOR"}),
    "compliance.exceptions.approve": frozenset(),  # ADMIN-only today
    "compliance.exceptions.revoke": frozenset({"OPERATOR"}),
    # Remediation — routers/compliance/remediation.py
    "compliance.remediation.maintenance_windows.manage": frozenset({"OPERATOR"}),
    "compliance.remediation.create": frozenset({"OPERATOR"}),
    "compliance.remediation.execute": frozenset({"OPERATOR"}),  # submit + dry-run
    "compliance.remediation.approve": frozenset({"OPERATOR"}),
    "compliance.remediation.rollback": frozenset(),  # ADMIN-only today
    # Findings — routers/compliance/findings.py (new, no prior require_role
    # to preserve; mirrors drift-event acknowledge's own role set)
    "compliance.findings.acknowledge": frozenset({"OPERATOR"}),
    # Policies — routers/compliance/policy_engine.py
    # create/publish/new-version/add-rule/assignments
    "compliance.policies.manage": frozenset({"OPERATOR"}),
    "compliance.policies.archive": frozenset(),  # ADMIN-only today
    "compliance.policies.import": frozenset(),  # ADMIN-only today
}
