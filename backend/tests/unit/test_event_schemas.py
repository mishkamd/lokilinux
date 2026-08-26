from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from lokilinux.events.schemas import EventIn


def _valid(**overrides):
    base = {"source": "agent", "type": "host.heartbeat.ok"}
    base.update(overrides)
    return base


def test_valid_event_accepted():
    ev = EventIn(**_valid())
    assert ev.severity == "INFO"
    assert ev.schema_version == 1


def test_unknown_source_rejected():
    with pytest.raises(ValidationError):
        EventIn(**_valid(source="not-a-real-source"))


def test_bad_type_pattern_rejected():
    with pytest.raises(ValidationError):
        EventIn(**_valid(type="Not Valid! Type"))


def test_type_too_short_rejected():
    with pytest.raises(ValidationError):
        EventIn(**_valid(type="ab"))


def test_unknown_severity_rejected():
    with pytest.raises(ValidationError):
        EventIn(**_valid(severity="SUPER_BAD"))


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        EventIn(**_valid(unexpected_field="nope"))


def test_oversize_payload_rejected():
    with pytest.raises(ValidationError):
        EventIn(**_valid(payload={"blob": "x" * 200_000}))


def test_payload_within_limit_accepted():
    ev = EventIn(**_valid(payload={"cpu": 42}))
    assert ev.payload == {"cpu": 42}


def test_timestamp_within_skew_accepted():
    ev = EventIn(**_valid(timestamp=datetime.now(timezone.utc) - timedelta(seconds=10)))
    assert ev.timestamp is not None


def test_timestamp_beyond_skew_rejected():
    with pytest.raises(ValidationError):
        EventIn(**_valid(timestamp=datetime.now(timezone.utc) - timedelta(hours=2)))


def test_naive_timestamp_treated_as_utc():
    ev = EventIn(**_valid(timestamp=datetime.utcnow()))
    assert ev.timestamp is not None
    assert ev.timestamp.tzinfo is not None
