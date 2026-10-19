"""
LokiLinux — per-process fixed-window counter for rate limits.

Used only while Redis is down (cache.incr_checked returned None), so the limit still
holds. Keys mirror the Redis keys they stand in for (e.g. "rate:ev:{principal}"), so the
events and OTLP routers share one bucket per principal, as they do in Redis.

ponytail: per-process counter. Each worker counts on its own, so during an outage the
effective limit is the configured value times the number of workers. Upgrade to a shared
last-good key if workers must agree during an outage.
"""


class LocalCounter:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = {}

    def increment(self, key: str, window: int) -> int:
        for k in [k for k in self._counts if k[1] < window]:
            del self._counts[k]
        self._counts[(key, window)] = self._counts.get((key, window), 0) + 1
        return self._counts[(key, window)]


local_counter = LocalCounter()
