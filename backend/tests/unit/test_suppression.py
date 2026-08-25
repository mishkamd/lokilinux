from datetime import datetime

from lokilinux.correlation.suppression import is_suppressed


def _dt(day: str, hh: int, mm: int) -> datetime:
    # 2026-08-24 is a Monday — pick offsets from there for deterministic weekdays.
    offsets = {"Mon": 24, "Tue": 25, "Wed": 26, "Thu": 27, "Fri": 28, "Sat": 29, "Sun": 30}
    return datetime(2026, 8, offsets[day], hh, mm)


def test_no_suppressions_never_suppresses():
    assert is_suppressed([], _dt("Sat", 12, 0)) is False


def test_inside_simple_window_is_suppressed():
    windows = [{"from": "Sat 00:00", "to": "Sun 23:59"}]
    assert is_suppressed(windows, _dt("Sat", 12, 0)) is True
    assert is_suppressed(windows, _dt("Sun", 23, 0)) is True


def test_outside_simple_window_is_not_suppressed():
    windows = [{"from": "Sat 00:00", "to": "Sun 23:59"}]
    assert is_suppressed(windows, _dt("Wed", 12, 0)) is False


def test_wraparound_window_across_week_boundary():
    windows = [{"from": "Fri 22:00", "to": "Mon 06:00"}]
    assert is_suppressed(windows, _dt("Fri", 23, 0)) is True
    assert is_suppressed(windows, _dt("Sun", 12, 0)) is True
    assert is_suppressed(windows, _dt("Mon", 5, 0)) is True
    assert is_suppressed(windows, _dt("Mon", 7, 0)) is False
    assert is_suppressed(windows, _dt("Wed", 12, 0)) is False


def test_malformed_entry_is_skipped_not_fatal():
    windows = [{"from": "not-a-day 99:99"}, {"from": "Sat 00:00", "to": "Sun 23:59"}]
    assert is_suppressed(windows, _dt("Sat", 12, 0)) is True  # 2nd entry still applies
    assert is_suppressed(windows, _dt("Wed", 12, 0)) is False


def test_multiple_windows_any_match_suppresses():
    windows = [
        {"from": "Mon 00:00", "to": "Mon 01:00"},
        {"from": "Wed 00:00", "to": "Wed 23:59"},
    ]
    assert is_suppressed(windows, _dt("Wed", 12, 0)) is True
