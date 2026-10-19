"""
CSV export guard (ROADMAP P2, CSV injection).

Spreadsheet apps evaluate a text cell that starts with = + - @ (or a tab/CR)
as a formula, so a CVE title like =HYPERLINK(...) would run on the reader's
machine. Such text gets a leading apostrophe, which the spreadsheet shows
as a literal. Numbers and None pass through untouched.
"""

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value):  # type: ignore[no-untyped-def]
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value
