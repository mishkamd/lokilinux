from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from lokilinux.correlation.suppression import is_suppressed
from lokilinux.signals.schemas import CorrelationRuleCreate

_BASE = dict(
    name="r", window_seconds=300, group_by=["host_id"],
    conditions=[{"signal": "cpu.high", "weight": 10}], threshold_score=10,
    incident_type="t", incident_severity="HIGH",
)


def test_group_by_other_than_host_id_is_rejected():
    with pytest.raises(ValidationError):
        CorrelationRuleCreate(**{**_BASE, "group_by": ["service"]})


@pytest.mark.parametrize(
    "bad",
    [[{"from": "Sat 00:00"}], [{"from": None, "to": "Sun 01:00"}], [{"from": "x", "to": "y"}]],
)
def test_malformed_suppression_is_rejected(bad):
    with pytest.raises(ValidationError):
        CorrelationRuleCreate(**{**_BASE, "suppressions": bad})


def test_well_formed_suppression_is_accepted():
    CorrelationRuleCreate(**{**_BASE, "suppressions": [{"from": "Sat 22:00", "to": "Mon 06:00"}]})


def test_a_stored_malformed_suppression_never_raises_or_suppresses():
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    assert is_suppressed([{"from": None, "to": "Sun 01:00"}], now) is False
