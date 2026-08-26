"""
LokiLinux — Phase B detectors: NormalizedEvent -> DetectedSignal(s).

Registry keyed by event type, fed by SignalProcessorWorker's
EVENT_NORMALIZED subscription.

Sustain counters (cpu/memory need 2 consecutive over-threshold samples) live
in Redis, keyed sig:thr:{host}:{metric}, reset on any under-threshold sample.
Thresholds are module-level constants for now (plan: "configurable later via
settings").
"""

from dataclasses import dataclass, field
from typing import Any

CPU_MEMORY_THRESHOLD = 90.0
DISK_THRESHOLD = 90.0
SUSTAIN_SAMPLES = 2
SUSTAIN_WINDOW_SEC = 600

# host.heartbeat.ok doesn't detect a new signal — it resolves an existing
# host.unreachable one. Handled specially in signal_service.py, not through
# the DETECTORS registry below.
RECOVERY_EVENT_TYPE = "host.heartbeat.ok"
RECOVERY_RESOLVES_SIGNAL_TYPE = "host.unreachable"


@dataclass
class DetectedSignal:
    type: str
    severity: str
    host_id: str | None
    service: str | None = None
    resource: str | None = None
    value: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


def detect_host_unreachable(event: Any) -> DetectedSignal | None:
    return DetectedSignal(type="host.unreachable", severity="CRITICAL", host_id=event.host_id)


def detect_job_failed(event: Any) -> DetectedSignal | None:
    payload = event.payload or {}
    return DetectedSignal(
        type="job.failed", severity="HIGH", host_id=event.host_id,
        metadata={"job_id": payload.get("job_id")},
    )


# Direct 1:1 detectors — pure functions, no I/O. metric.sample is handled by
# detect_metric_samples() below (async: needs Redis for the sustain counter,
# and can emit 0-3 signals from one event instead of exactly one).
DETECTORS = {
    "host.unreachable": detect_host_unreachable,
    "job.failed": detect_job_failed,
}

METRIC_SAMPLE_EVENT_TYPE = "metric.sample"

_METRIC_RULES = (
    # (payload key, signal type, threshold, samples required before firing)
    ("cpu", "cpu.high", CPU_MEMORY_THRESHOLD, SUSTAIN_SAMPLES),
    ("memory", "memory.high", CPU_MEMORY_THRESHOLD, SUSTAIN_SAMPLES),
    ("disk", "disk.usage.high", DISK_THRESHOLD, 1),
)


async def detect_metric_samples(event: Any, cache: Any) -> list[DetectedSignal]:
    payload = event.payload or {}
    detected: list[DetectedSignal] = []
    for metric_key, sig_type, threshold, sustain in _METRIC_RULES:
        value = payload.get(metric_key)
        if value is None:
            continue
        counter_key = f"sig:thr:{event.host_id}:{metric_key}"
        if value < threshold:
            await cache.invalidate(counter_key)
            continue
        if sustain <= 1:
            detected.append(DetectedSignal(type=sig_type, severity="HIGH", host_id=event.host_id, value=value))
            continue
        count = await cache.incr(counter_key, ttl=SUSTAIN_WINDOW_SEC)
        if count >= sustain:
            detected.append(DetectedSignal(type=sig_type, severity="HIGH", host_id=event.host_id, value=value))
    return detected
