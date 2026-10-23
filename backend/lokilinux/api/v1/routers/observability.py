"""
LokiLinux — Observability router: pipeline health snapshot.

Reads directly from the prometheus_client metric objects this pipeline owns
(metrics.py) rather than the entire global REGISTRY, which also carries
unrelated KMS/job-signing counters from elsewhere in the app.

"workers" carries the last-seen timestamp of each pipeline worker (utils/liveness.py) and of
the last successful ClickHouse flush per buffer. The event, signal and incident workers beat
on a timer, so a stale timestamp means a stuck worker; correlation_worker has no timer and
only beats when it handles a signal, so a quiet pipeline looks stale there too.
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
from lokilinux.utils import liveness

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
        "workers": liveness.snapshot(),
    }
