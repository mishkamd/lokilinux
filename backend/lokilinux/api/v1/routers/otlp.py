"""
LokiLinux — OpenTelemetry OTLP/HTTP ingestion (Task G1).

Accepts OTLP/HTTP protobuf (`content-type: application/x-protobuf`) on the
standard OTLP collector paths. Logs and spans are translated
(lokilinux.otlp.translate) into the same EventIn used by POST /api/v1/events
and published to EVENT_RAW.otel — EventProcessorWorker (Task A5) owns
dedup/fingerprint/persist from there, unchanged. No span-storage engine:
traces become trace-reference events, queryable via the existing
GET /api/v1/events?source=otel. Auth + rate limiting mirror routers/events.py
exactly (JWT via get_current_user; one rate:ev:{principal}:{minute} bucket
per HTTP call, shared with the plain events API).
"""

from datetime import datetime
from typing import Any
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
import structlog

from lokilinux.auth.dependencies import get_current_user
from lokilinux.config import get_settings
from lokilinux.dependencies import get_cache, get_nats
from lokilinux.events.schemas import EventIn
from lokilinux.nats_topics import EVENT_RAW
from lokilinux.otlp.translate import _attrs_to_dict, log_record_to_event_in, span_to_event_in

logger = structlog.get_logger()

router = APIRouter()

_TENANT_ID = "default"
_PROTOBUF_MEDIA_TYPE = "application/x-protobuf"


async def _enforce_rate_limit(cache: Any, current_user: dict[str, Any]) -> None:
    principal = current_user.get("id") or "unknown"
    settings = get_settings()
    window = int(datetime.now().timestamp() // 60)
    count = await cache.incr(f"rate:ev:{principal}:{window}", ttl=90)
    if count > settings.event_rate_per_agent_per_min:
        raise HTTPException(status_code=429, detail="event rate limit exceeded")


async def _publish(nats: Any, event: EventIn, event_id: str | None) -> None:
    payload = {**event.model_dump(mode="json"), "tenant_id": _TENANT_ID}
    if event_id:
        payload["event_id"] = event_id
    await nats.publish(f"{EVENT_RAW}.{event.source}", json.dumps(payload).encode())


@router.post("/logs")
async def ingest_logs(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
    cache: Any = Depends(get_cache),
    nats: Any = Depends(get_nats),
) -> Response:
    req = ExportLogsServiceRequest()
    try:
        req.ParseFromString(await request.body())
    except DecodeError:
        raise HTTPException(status_code=400, detail="malformed OTLP protobuf")

    await _enforce_rate_limit(cache, current_user)

    rejected = 0
    errors: list[str] = []
    for resource_logs in req.resource_logs:
        resource_attrs = _attrs_to_dict(resource_logs.resource.attributes)
        for scope_logs in resource_logs.scope_logs:
            for log_record in scope_logs.log_records:
                try:
                    event, event_id = log_record_to_event_in(log_record, resource_attrs)
                except Exception as exc:
                    rejected += 1
                    errors.append(str(exc))
                    continue
                await _publish(nats, event, event_id)

    resp = ExportLogsServiceResponse()
    if rejected:
        resp.partial_success.rejected_log_records = rejected
        resp.partial_success.error_message = "; ".join(errors[:10])
        logger.warning("otlp.logs.partial_reject", rejected=rejected)
    return Response(content=resp.SerializeToString(), media_type=_PROTOBUF_MEDIA_TYPE)


@router.post("/traces")
async def ingest_traces(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
    cache: Any = Depends(get_cache),
    nats: Any = Depends(get_nats),
) -> Response:
    req = ExportTraceServiceRequest()
    try:
        req.ParseFromString(await request.body())
    except DecodeError:
        raise HTTPException(status_code=400, detail="malformed OTLP protobuf")

    await _enforce_rate_limit(cache, current_user)

    rejected = 0
    errors: list[str] = []
    for resource_spans in req.resource_spans:
        resource_attrs = _attrs_to_dict(resource_spans.resource.attributes)
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                try:
                    event, event_id = span_to_event_in(span, resource_attrs)
                except Exception as exc:
                    rejected += 1
                    errors.append(str(exc))
                    continue
                await _publish(nats, event, event_id)

    resp = ExportTraceServiceResponse()
    if rejected:
        resp.partial_success.rejected_spans = rejected
        resp.partial_success.error_message = "; ".join(errors[:10])
        logger.warning("otlp.traces.partial_reject", rejected=rejected)
    return Response(content=resp.SerializeToString(), media_type=_PROTOBUF_MEDIA_TYPE)
