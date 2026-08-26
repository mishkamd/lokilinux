"""
LokiLinux — Observability router: pipeline health snapshot.

Reads directly from the prometheus_client metric objects this pipeline owns
(metrics.py) rather than the entire global REGISTRY, which also carries
unrelated KMS/job-signing counters from elsewhere in the app.

Not included here (documented simplification, not an oversight): per-worker
liveness timestamps. Tracking those would mean every worker touching a
shared registry on its hot path — a broad instrumentation sweep across
~10 files for a "last active" signal that /health already answers at the
process level. A real per-worker heartbeat is a reasonable follow-up, not
something this snapshot endpoint needs to block on.
"""

from typing import Any

from fastapi import APIRouter, Depends

from lokilinux.auth.dependencies import get_current_user
from lokilinux.metrics import (
    ch_operation_duration_seconds,
    clickhouse_insert_errors_total,
    correlation_duration_seconds,
    event_buffer_depth,
    events_dropped_total,
    events_received_total,
    incidents_created_total,
    signals_detected_total,
)

router = APIRouter()


def _samples(metric: Any) -> list[dict[str, Any]]:
    return [
        {"name": sample.name, "labels": sample.labels, "value": sample.value}
        for family in metric.collect()
        for sample in family.samples
    ]


@router.get("/pipeline")
async def pipeline_snapshot(_: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "events_received": _samples(events_received_total),
        "events_dropped": _samples(events_dropped_total),
        "signals_detected": _samples(signals_detected_total),
        "incidents_created": _samples(incidents_created_total),
        "clickhouse_insert_errors": _samples(clickhouse_insert_errors_total),
        "buffer_depth": _samples(event_buffer_depth),
        "correlation_duration": _samples(correlation_duration_seconds),
        "clickhouse_operation_duration": _samples(ch_operation_duration_seconds),
    }
