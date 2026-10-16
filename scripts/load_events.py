#!/usr/bin/env python3
"""LokiLinux — observability pipeline load generator (plan G3-1).

Publishes synthetic EventIn-shaped JSON to lokilinux.events.raw.loadtest at
a target sustained rate, ramping up over the first 10% of the run and back
down over the last 10% (linear, simplest ramp that produces the three named
profiles from the plan: 1K/10K/100K events/sec).

Standalone — deliberately does not import anything from lokilinux.* (the
backend package), just matches EventIn's shape by hand, so this script
isn't coupled to backend internals and can run from anywhere nats-py is
installed (e.g. `backend/.venv/bin/python3 scripts/load_events.py ...`).

This is a tool, not logic under test — no pytest suite around a CLI. Smoke
test it directly against a local NATS:

    python scripts/load_events.py --rate 1000 --duration 2 --nats-url nats://localhost:4222
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import nats

SUBJECT = "lokilinux.events.raw.loadtest"
RAMP_FRACTION = 0.10


def _build_event(seq: int) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "tenant_id": "default",
            "source": "external",
            "type": "loadtest.synthetic",
            "severity": "INFO",
            "host_id": f"loadtest-host-{seq % 50}",
            "service": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"seq": seq},
        }
    ).encode()


def _target_rate(elapsed: float, duration: float, peak_rate: float) -> float:
    """Linear ramp-up over the first RAMP_FRACTION of duration, sustain,
    ramp-down over the last RAMP_FRACTION — the simplest curve that hits
    the three named profiles (1K/10K/100K eps) without a bespoke ramp
    library."""
    ramp = duration * RAMP_FRACTION
    if ramp <= 0:
        return peak_rate
    if elapsed < ramp:
        return peak_rate * (elapsed / ramp)
    if elapsed > duration - ramp:
        remaining = max(0.0, duration - elapsed)
        return peak_rate * (remaining / ramp)
    return peak_rate


async def _publisher(nc, worker_id: int, peak_rate: float, duration: float, start: float) -> int:
    sent = 0
    seq = worker_id
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= duration:
            break
        rate = _target_rate(elapsed, duration, peak_rate)
        remaining = max(0.0, duration - elapsed)
        # Clamp: near the ramp edges `rate` can be a tiny-but-nonzero
        # fraction of peak_rate, and 1.0/rate for a near-zero rate would
        # sleep for minutes — cap at 50ms so the loop keeps re-checking
        # elapsed/duration at a sane cadence regardless of how slow the
        # ramp currently is.
        if rate <= 0:
            await asyncio.sleep(min(0.05, remaining) if remaining > 0 else 0)
            continue
        await nc.publish(SUBJECT, _build_event(seq))
        sent += 1
        seq += 1
        await asyncio.sleep(min(1.0 / rate, 0.05, remaining) if remaining > 0 else 0)
    return sent


async def run(rate: int, duration: float, nats_url: str, workers: int) -> None:
    nc = await nats.connect(nats_url)
    try:
        per_worker_rate = rate / workers
        start = time.monotonic()
        results = await asyncio.gather(
            *[_publisher(nc, w, per_worker_rate, duration, start) for w in range(workers)]
        )
        total = sum(results)
        elapsed = time.monotonic() - start
        print(
            f"published {total} events in {elapsed:.2f}s "
            f"(target rate={rate}/s, actual avg={total / elapsed:.1f}/s)"
        )
    finally:
        await nc.drain()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rate",
        type=int,
        choices=(1000, 10000, 100000),
        required=True,
        help="peak sustained events/sec",
    )
    parser.add_argument("--duration", type=float, default=30.0, help="total run time in seconds")
    parser.add_argument("--nats-url", default="nats://localhost:4222")
    parser.add_argument(
        "--workers", type=int, default=10, help="publisher coroutines sharing the target rate"
    )
    args = parser.parse_args()

    asyncio.run(run(args.rate, args.duration, args.nats_url, args.workers))


if __name__ == "__main__":
    main()
