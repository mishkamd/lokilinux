import time

from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status

from lokilinux.otlp.translate import log_record_to_event_in, span_to_event_in

_TRACE_ID = bytes.fromhex("0123456789abcdef0123456789abcdef")[:16]
_SPAN_ID = bytes.fromhex("0123456789abcdef")
# EventIn rejects timestamps outside event_max_clock_skew_sec (default 300s) —
# every record here needs a "now"-ish timestamp, not a fixed historical one.
_NOW_NANOS = int(time.time() * 1e9)


def _log_record(**overrides) -> LogRecord:
    lr = LogRecord(
        time_unix_nano=overrides.pop("time_unix_nano", _NOW_NANOS),
        severity_number=overrides.pop("severity_number", 9),
        body=AnyValue(string_value=overrides.pop("body", "hello")),
    )
    for k, v in overrides.items():
        setattr(lr, k, v)
    return lr


# ── severity mapping ─────────────────────────────────────────────────────────


def test_severity_mapping_covers_every_documented_range():
    cases = {1: "DEBUG", 8: "DEBUG", 9: "INFO", 12: "INFO", 13: "WARNING",
             16: "WARNING", 17: "ERROR", 20: "ERROR", 21: "CRITICAL", 24: "CRITICAL"}
    for number, expected in cases.items():
        event, _ = log_record_to_event_in(_log_record(severity_number=number), {})
        assert event.severity == expected, number


def test_unspecified_severity_defaults_to_info():
    event, _ = log_record_to_event_in(_log_record(severity_number=0), {})
    assert event.severity == "INFO"


# ── resource attribute extraction ───────────────────────────────────────────


def test_resource_attributes_populate_host_and_service():
    resource_attrs = {"service.name": "checkout-api", "host.id": "host-42"}
    event, _ = log_record_to_event_in(_log_record(), resource_attrs)
    assert event.service == "checkout-api"
    assert event.host_id == "host-42"


def test_missing_resource_attributes_leave_host_and_service_none():
    event, _ = log_record_to_event_in(_log_record(), {})
    assert event.service is None
    assert event.host_id is None


# ── event_id determinism ─────────────────────────────────────────────────────


def test_log_event_id_deterministic_for_identical_input():
    lr = _log_record(trace_id=_TRACE_ID, span_id=_SPAN_ID)
    _, id_a = log_record_to_event_in(lr, {})
    _, id_b = log_record_to_event_in(lr, {})
    assert id_a == id_b
    assert id_a is not None


def test_log_event_id_differs_for_different_timestamp():
    lr_a = _log_record(trace_id=_TRACE_ID, span_id=_SPAN_ID, time_unix_nano=_NOW_NANOS)
    lr_b = _log_record(trace_id=_TRACE_ID, span_id=_SPAN_ID, time_unix_nano=_NOW_NANOS + 1)
    _, id_a = log_record_to_event_in(lr_a, {})
    _, id_b = log_record_to_event_in(lr_b, {})
    assert id_a != id_b


def test_log_event_id_none_when_no_timestamp_at_all():
    lr = LogRecord(severity_number=9, body=AnyValue(string_value="x"))
    _, event_id = log_record_to_event_in(lr, {})
    assert event_id is None


# ── payload shape ────────────────────────────────────────────────────────────


def test_log_payload_carries_body_attributes_and_trace_context():
    lr = _log_record(trace_id=_TRACE_ID, span_id=_SPAN_ID)
    lr.attributes.append(KeyValue(key="k", value=AnyValue(string_value="v")))
    event, _ = log_record_to_event_in(lr, {})
    assert event.payload["body"] == "hello"
    assert event.payload["attributes"] == {"k": "v"}
    assert event.payload["trace_id"] == _TRACE_ID.hex()
    assert event.payload["span_id"] == _SPAN_ID.hex()
    assert event.type == "otel.log"
    assert event.source == "otel"


def test_log_record_without_attributes_does_not_crash():
    event, _ = log_record_to_event_in(_log_record(), {})
    assert event.payload["attributes"] == {}


# ── spans ─────────────────────────────────────────────────────────────────


def _span(**overrides) -> Span:
    span = Span(
        trace_id=_TRACE_ID,
        span_id=_SPAN_ID,
        name=overrides.pop("name", "GET /checkout"),
        start_time_unix_nano=overrides.pop("start_time_unix_nano", _NOW_NANOS),
        end_time_unix_nano=overrides.pop("end_time_unix_nano", _NOW_NANOS + 250_000_000),
    )
    for k, v in overrides.items():
        setattr(span, k, v)
    return span


def test_span_payload_has_identifiers_and_duration_no_full_span_dump():
    event, event_id = span_to_event_in(_span(), {})
    assert event.type == "otel.trace"
    assert event.payload["trace_id"] == _TRACE_ID.hex()
    assert event.payload["span_id"] == _SPAN_ID.hex()
    assert event.payload["name"] == "GET /checkout"
    assert event.payload["duration_ms"] == 250.0
    assert "events" not in event.payload  # no span-storage engine — only the reference fields
    assert event_id is not None


def test_span_status_error_maps_to_error_severity():
    span = _span()
    span.status.CopyFrom(Status(code=Status.StatusCode.STATUS_CODE_ERROR))
    event, _ = span_to_event_in(span, {})
    assert event.payload["status"] == "ERROR"
    assert event.severity == "ERROR"


def test_span_status_ok_maps_to_info_severity():
    span = _span()
    span.status.CopyFrom(Status(code=Status.StatusCode.STATUS_CODE_OK))
    event, _ = span_to_event_in(span, {})
    assert event.severity == "INFO"


def test_span_event_id_none_without_trace_or_span_id():
    span = Span(name="orphan", start_time_unix_nano=_NOW_NANOS, end_time_unix_nano=_NOW_NANOS + 1_000_000_000)
    _, event_id = span_to_event_in(span, {})
    assert event_id is None
