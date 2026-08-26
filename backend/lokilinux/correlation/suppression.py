"""
LokiLinux — correlation rule suppression windows (maintenance windows), v1.

Simple weekly recurring windows: [{"from": "Sat 00:00", "to": "Sun 23:59"}].
Minute-of-week (0-10079, Monday 00:00 = 0) makes a window that crosses the
week boundary (e.g. "Fri 22:00" -> "Mon 06:00") a plain interval check
instead of special-cased date arithmetic.
"""

from datetime import datetime

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _parse_point(point: str) -> int:
    day, hh_mm = point.split(" ", 1)
    hours, minutes = hh_mm.split(":")
    return _DAYS.index(day) * 1440 + int(hours) * 60 + int(minutes)


def is_suppressed(suppressions: list, now: datetime) -> bool:
    if not suppressions:
        return False
    now_minute = now.weekday() * 1440 + now.hour * 60 + now.minute
    for window in suppressions:
        try:
            start = _parse_point(window["from"])
            end = _parse_point(window["to"])
        except (KeyError, ValueError, IndexError):
            continue  # malformed entry — skip it, don't let it suppress everything
        if start <= end:
            if start <= now_minute <= end:
                return True
        else:  # wraps past the week boundary
            if now_minute >= start or now_minute <= end:
                return True
    return False
