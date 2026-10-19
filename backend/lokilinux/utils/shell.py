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

import ipaddress
import re
import shlex


def q(value: object) -> str:
    """Quote one value for safe interpolation into a generated shell
    command line. Always converts to str first — config values arrive from
    JSON/YAML and may already be int/bool."""
    return shlex.quote(str(value))


# Same charset as the agent's packageNameRe (agent/internal/modules/package_updater.go):
# alphanumerics and + . _ : -, never a leading "-". No shell metacharacters can get
# through. Bounded to fit varchar(255).
PACKAGE_NAME_RE = re.compile(r"[A-Za-z0-9+._:][A-Za-z0-9+._:-]{0,254}")

_HOST_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"{_HOST_LABEL}(?:\.{_HOST_LABEL})*")


def valid_package_name(name: object) -> bool:
    return isinstance(name, str) and PACKAGE_NAME_RE.fullmatch(name) is not None


def valid_host(host: str) -> bool:
    """A hostname or an IP literal. Anything else never reaches a command."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return len(host) <= 253 and _HOSTNAME_RE.fullmatch(host) is not None
