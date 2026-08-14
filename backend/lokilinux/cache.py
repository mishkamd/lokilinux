"""
LokiLinux — Redis cache layer (cache-aside pattern)

TTL constants (O6 — standardized):
  AGENT_STATUS  30 s   — live heartbeat data, short-lived
  JOB_STATUS    60 s   — job state changes frequently
  CVE_DATA      3600 s — CVE feed stable within an hour
  SERVER_LIST   86400 s (not used directly; server list uses AGENT_STATUS scope)
  DASHBOARD     60 s   — aggregate rollups, tolerable staleness for a summary view
"""

import json
from typing import Any, Optional

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

# ── Standardized TTLs (seconds) ───────────────────────────────────────────────
TTL_AGENT_STATUS: int = 30
TTL_JOB_STATUS: int = 60
TTL_CVE_DATA: int = 3600
TTL_SERVER_LIST: int = 86400
TTL_DASHBOARD: int = 60

# Key naming convention:
#   agent:{id}:status | agent:{id}:detail
#   job:{id}:status
#   cve:{id}:details | cve:database:version
#   server:list:{limit}:{cursor}
#   vulnerability:{agent_id}:list


class RedisCache:
    """Async Redis cache with cache-aside helpers and pattern invalidation."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._client: Optional[aioredis.Redis] = None  # type: ignore[type-arg]

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            self.url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
        )
        logger.info("redis.connected", url=self.url)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())  # type: ignore[union-attr]
        except Exception:
            return False

    # ── Core ops ──────────────────────────────────────────────────────────────

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self._client.exists(key))  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("cache.exists_error", key=key, error=str(exc))
            return False

    async def get_cached(self, key: str) -> Optional[Any]:
        try:
            raw = await self._client.get(key)  # type: ignore[union-attr]
            return json.loads(raw) if raw is not None else None
        except Exception as exc:
            logger.warning("cache.get_error", key=key, error=str(exc))
            return None

    async def set_cached(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> None:
        try:
            await self._client.set(  # type: ignore[union-attr]
                key,
                json.dumps(value, default=str),
                ex=ttl,
            )
        except Exception as exc:
            logger.warning("cache.set_error", key=key, error=str(exc))

    async def incr(self, key: str, ttl: int) -> int:
        """Atomic INCR + EXPIRE, e.g. for rate-limit counters. Fails open (returns 0) on Redis errors."""
        try:
            pipe = self._client.pipeline()  # type: ignore[union-attr]
            pipe.incr(key)
            pipe.expire(key, ttl)
            results = await pipe.execute()
            return int(results[0])
        except Exception as exc:
            logger.warning("cache.incr_error", key=key, error=str(exc))
            return 0

    async def invalidate(self, key: str) -> None:
        try:
            await self._client.delete(key)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("cache.invalidate_error", key=key, error=str(exc))

    async def invalidate_pattern(self, pattern: str) -> None:
        """Delete all keys matching a glob pattern (use sparingly — O(N))."""
        try:
            keys = await self._client.keys(pattern)  # type: ignore[union-attr]
            if keys:
                await self._client.delete(*keys)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("cache.invalidate_pattern_error", pattern=pattern, error=str(exc))

    # ── Domain-level invalidation helpers ────────────────────────────────────

    async def invalidate_agent(self, agent_id: str) -> None:
        await self.invalidate_pattern(f"agent:{agent_id}:*")
        await self.invalidate_pattern(f"vulnerability:{agent_id}:*")

    async def invalidate_cve_database(self) -> None:
        await self.invalidate_pattern("cve:*")
        await self.invalidate_pattern("vulnerability:*")
