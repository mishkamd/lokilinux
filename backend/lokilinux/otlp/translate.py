"""
LokiLinux — OpenTelemetry OTLP -> EventIn translation (Task G1).

Pure functions: an OTLP protobuf record in, an EventIn (+ deterministic
event_id when possible) out. No I/O, no NATS, no auth — the router
(api/v1/routers/otlp.py) owns publishing to EVENT_RAW.otel, same as every
other producer. Logs become source="otel" events; spans become
trace-reference events (no span-storage engine — payload carries only
identifiers + timing, never the full span).

event_id is derived from (record kind, trace_id, span_id, time_unix_nano) via
uuid5 — a real OTLP collector retries the *exact same* protobuf on transient
failure (same nanosecond timestamp), so this makes retries dedupe through the
EventProcessorWorker's existing `ev:dedup:{event_id}` key (workers/
event_processor.py) instead of creating duplicate events. When the record has
no timestamp (time_unix_nano/start_time_unix_nano == 0 — malformed/unusual
input), we deliberately return event_id=None rather than dedupe on
under-specified identity, which would silently drop unrelated same-batch
records as "duplicates".
"""

from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord
from opentelemetry.proto.trace.v1.trace_pb2 import Span

from lokilinux.events.schemas import EventIn

_SEVERITY_RANGES = (
    (1, 8, "DEBUG"),
    (9, 12, "INFO"),
    (13, 16, "WARNING"),
    (17, 20, "ERROR"),
    (21, 24, "CRITICAL"),
)
_STATUS_CODE_NAMES = {0: "UNSET", 1: "OK", 2: "ERROR"}


def _severity_from_number(severity_number: int) -> str:
    for lo, hi, name in _SEVERITY_RANGES:
        if lo <= severity_number <= hi:
            return name
    return "INFO"  # SEVERITY_NUMBER_UNSPECIFIED (0) or out-of-range


def _any_value_to_python(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind == "string_value":
        return value.string_value
    if kind == "bool_value":
        return value.bool_value
    if kind == "int_value":
        return value.int_value
    if kind == "double_value":
        return value.double_value
    if kind == "bytes_value":
        return value.bytes_value.hex()
    return None  # array_value/kvlist_value — not flattened (MVP scope)


def _attrs_to_dict(attributes: list[KeyValue]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kv in attributes:
        v = _any_value_to_python(kv.value)
        if v is not None:
            out[kv.key] = v
    return out


def _resource_attr(resource_attrs: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        v = resource_attrs.get(key)
        if v:
            return str(v)
    return None


def _event_id(*parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, "|".join(parts))


def log_record_to_event_in(
    log_record: LogRecord, resource_attrs: dict[str, Any]
) -> tuple[EventIn, str | None]:
    trace_id_hex = log_record.trace_id.hex() or None
    span_id_hex = log_record.span_id.hex() or None
    ts_nanos = log_record.time_unix_nano or log_record.observed_time_unix_nano

    payload: dict[str, Any] = {
        "body": _any_value_to_python(log_record.body),
        "attributes": _attrs_to_dict(log_record.attributes),
    }
    if trace_id_hex:
        payload["trace_id"] = trace_id_hex
    if span_id_hex:
        payload["span_id"] = span_id_hex
    if log_record.severity_text:
        payload["severity_text"] = log_record.severity_text

    event = EventIn(
        source="otel",
        type="otel.log",
        severity=_severity_from_number(log_record.severity_number),
        host_id=_resource_attr(resource_attrs, "host.id", "host.name", "service.instance.id"),
        service=_resource_attr(resource_attrs, "service.name"),
        timestamp=datetime.fromtimestamp(ts_nanos / 1e9, tz=timezone.utc) if ts_nanos else None,
        payload=payload,
    )
    event_id = (
        str(_event_id("otel.log", trace_id_hex or "", span_id_hex or "", str(ts_nanos)))
        if ts_nanos
        else None
    )
    return event, event_id


def span_to_event_in(
    span: Span, resource_attrs: dict[str, Any]
) -> tuple[EventIn, str | None]:
    trace_id_hex = span.trace_id.hex() or None
    span_id_hex = span.span_id.hex() or None
    parent_span_id_hex = span.parent_span_id.hex() or None
    start_nanos = span.start_time_unix_nano
    end_nanos = span.end_time_unix_nano

    status_code = _STATUS_CODE_NAMES.get(span.status.code, "UNSET")
    duration_ms = (end_nanos - start_nanos) / 1e6 if start_nanos and end_nanos else None

    payload: dict[str, Any] = {
        "trace_id": trace_id_hex,
        "span_id": span_id_hex,
        "parent_span_id": parent_span_id_hex,
        "name": span.name,
        "duration_ms": duration_ms,
        "status": status_code,
    }

    event = EventIn(
        source="otel",
        type="otel.trace",
        severity="ERROR" if status_code == "ERROR" else "INFO",
        host_id=_resource_attr(resource_attrs, "host.id", "host.name", "service.instance.id"),
        service=_resource_attr(resource_attrs, "service.name"),
        timestamp=datetime.fromtimestamp(start_nanos / 1e9, tz=timezone.utc) if start_nanos else None,
        payload=payload,
    )
    event_id = (
        str(_event_id("otel.trace", trace_id_hex or "", span_id_hex or ""))
        if trace_id_hex and span_id_hex
        else None
    )
    return event, event_id
