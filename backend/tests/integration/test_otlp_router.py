import json
import time

import pytest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

_HEADERS = {"content-type": "application/x-protobuf"}
_NOW_NANOS = int(time.time() * 1e9)


def _logs_request(*, time_unix_nano: int = _NOW_NANOS, service: str = "checkout-api") -> bytes:
    req = ExportLogsServiceRequest()
    rl = req.resource_logs.add()
    rl.resource.attributes.append(KeyValue(key="service.name", value=AnyValue(string_value=service)))
    sl = rl.scope_logs.add()
    lr = sl.log_records.add()
    lr.time_unix_nano = time_unix_nano
    lr.severity_number = 9
    lr.body.string_value = "checkout completed"
    return req.SerializeToString()


def _traces_request(*, start_time_unix_nano: int = _NOW_NANOS) -> bytes:
    req = ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    rs.resource.attributes.append(KeyValue(key="service.name", value=AnyValue(string_value="checkout-api")))
    ss = rs.scope_spans.add()
    span = ss.spans.add()
    span.trace_id = bytes(range(16))
    span.span_id = bytes(range(8))
    span.name = "GET /checkout"
    span.start_time_unix_nano = start_time_unix_nano
    span.end_time_unix_nano = start_time_unix_nano + 250_000_000
    return req.SerializeToString()


# ── POST /api/v1/otlp/v1/logs ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_logs_accepted_and_published(client, fake_nats):
    resp = await client.post("/api/v1/otlp/v1/logs", content=_logs_request(), headers=_HEADERS)
    assert resp.status_code == 200

    parsed = ExportLogsServiceResponse()
    parsed.ParseFromString(resp.content)
    assert parsed.partial_success.rejected_log_records == 0

    assert len(fake_nats.published) == 1
    subject, payload = fake_nats.published[0]
    assert subject == "lokilinux.events.raw.otel"
    assert b'"otel.log"' in payload
    assert b'"checkout-api"' in payload


@pytest.mark.asyncio
async def test_post_logs_malformed_protobuf_returns_400(client):
    resp = await client.post("/api/v1/otlp/v1/logs", content=b"not a protobuf message \xff\xfe", headers=_HEADERS)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_logs_invalid_record_reported_as_partial_success(client, fake_nats):
    # Timestamp far outside the allowed clock-skew window (EventIn validator) —
    # translation succeeds but EventIn(**) construction raises per-record.
    stale_nanos = int((time.time() - 10_000) * 1e9)
    resp = await client.post(
        "/api/v1/otlp/v1/logs", content=_logs_request(time_unix_nano=stale_nanos), headers=_HEADERS
    )
    assert resp.status_code == 200

    parsed = ExportLogsServiceResponse()
    parsed.ParseFromString(resp.content)
    assert parsed.partial_success.rejected_log_records == 1
    assert parsed.partial_success.error_message
    assert len(fake_nats.published) == 0


@pytest.mark.asyncio
async def test_post_logs_rate_limit_exceeded(client, monkeypatch):
    from types import SimpleNamespace

    import lokilinux.api.v1.routers.otlp as otlp_mod

    monkeypatch.setattr(otlp_mod, "get_settings", lambda: SimpleNamespace(event_rate_per_agent_per_min=1))

    first = await client.post("/api/v1/otlp/v1/logs", content=_logs_request(), headers=_HEADERS)
    assert first.status_code == 200
    second = await client.post("/api/v1/otlp/v1/logs", content=_logs_request(), headers=_HEADERS)
    assert second.status_code == 429


# ── POST /api/v1/otlp/v1/traces ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_traces_accepted_and_published_as_trace_reference_event(client, fake_nats):
    resp = await client.post("/api/v1/otlp/v1/traces", content=_traces_request(), headers=_HEADERS)
    assert resp.status_code == 200

    parsed = ExportTraceServiceResponse()
    parsed.ParseFromString(resp.content)
    assert parsed.partial_success.rejected_spans == 0

    assert len(fake_nats.published) == 1
    subject, payload = fake_nats.published[0]
    assert subject == "lokilinux.events.raw.otel"
    body = json.loads(payload)
    assert body["type"] == "otel.trace"
    assert body["payload"]["duration_ms"] == 250.0


@pytest.mark.asyncio
async def test_post_traces_malformed_protobuf_returns_400(client):
    resp = await client.post("/api/v1/otlp/v1/traces", content=b"\xff\xfe\x00garbage", headers=_HEADERS)
    assert resp.status_code == 400
