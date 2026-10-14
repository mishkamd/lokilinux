"""CSV formula escaping (ROADMAP P2, CSV injection)."""

import pytest

from lokilinux.utils.csv_safe import csv_cell


@pytest.mark.parametrize(
    "value",
    ["=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"],
)
def test_formula_prefixes_are_neutralised(value):
    assert csv_cell(value) == "'" + value


def test_plain_text_numbers_and_none_pass_through():
    assert csv_cell("CVE-2026-1234") == "CVE-2026-1234"
    assert csv_cell(7.5) == 7.5
    assert csv_cell(-3) == -3
    assert csv_cell(None) is None
