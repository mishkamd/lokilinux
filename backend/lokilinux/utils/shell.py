"""
LokiLinux — shell-quoting helper for compile-down (Partea III of the
migration plan). Every Linux/Check node compiles to a `CUSTOM_COMMAND` Job
server-side (services/workflow_engine.py) — this is the ONE place that
interpolation happens, so it's the one place that has to get quoting right.

`shlex.quote` is the actual security boundary: it makes any string a single
literal shell argument no matter what metacharacters it contains — a
service name of `nginx; rm -rf /` becomes a harmless (if wrong) argument to
`systemctl`, never a second command. The Compile-Down Rule (plan Partea III
§3) is what makes a `service`/`system`/`file`/`package` node a *safe*
structured operation rather than shell-with-extra-steps — this module is
where that promise is kept.
"""

import shlex


def q(value: object) -> str:
    """Quote one value for safe interpolation into a generated shell
    command line. Always converts to str first — config values arrive from
    JSON/YAML and may already be int/bool."""
    return shlex.quote(str(value))
