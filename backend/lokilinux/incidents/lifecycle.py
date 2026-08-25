"""
LokiLinux — incident status transition rules.
"""

TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED"},
    "ACKNOWLEDGED": {"IN_PROGRESS", "RESOLVED"},
    "IN_PROGRESS": {"RESOLVED"},
    "RESOLVED": {"CLOSED", "OPEN"},  # OPEN = reopen
    "CLOSED": set(),
}


class IllegalTransition(ValueError):
    pass


def assert_legal(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"cannot transition incident {current} -> {target}")
