"""
LokiLinux — last-seen timestamps for the observability pipeline's background workers.

Workers run in the API process, so a module-level dict is enough: each worker calls
beat() from a loop or handler it already has, and /observability/pipeline reads it back.

shortcut: per process. If workers ever move to their own container, publish the beats
through Redis instead.
"""

from datetime import datetime, timezone

_last_seen: dict[str, datetime] = {}


def beat(name: str) -> None:
    _last_seen[name] = datetime.now(timezone.utc)


def snapshot() -> dict[str, str]:
    return {name: ts.isoformat() for name, ts in sorted(_last_seen.items())}
