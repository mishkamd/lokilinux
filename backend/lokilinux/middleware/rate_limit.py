"""
LokiLinux — Redis-backed rate limit middleware.

Reads security.rate_limit_enabled / security.rate_limit_per_minute from the
Setting table via app.state (populated during lifespan, so this middleware
can be registered at import time and only touch app.state per-request).

ponytail: fixed 60s window (not sliding) — good enough for abuse protection;
upgrade to a sliding window if burst-at-window-boundary becomes a real problem.
Settings are cached in Redis for 30s so a config change doesn't take effect
faster than that, and normal traffic doesn't hit Postgres per-request.
"""

import time

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from lokilinux.settings_schema import get_setting_value

logger = structlog.get_logger()

_CONFIG_CACHE_KEY = "settings:security:rate_limit"
_EXEMPT_PATHS = {"/health", "/ready"}


async def _rate_limit_config(cache, session_factory) -> tuple[bool, int]:
    cached = await cache.get_cached(_CONFIG_CACHE_KEY)
    if cached is not None:
        return bool(cached["enabled"]), int(cached["limit"])

    try:
        async with session_factory() as db:
            enabled = await get_setting_value(db, "security.rate_limit_enabled")
            limit = await get_setting_value(db, "security.rate_limit_per_minute")
    except Exception:
        # ponytail: fail-open — if the settings DB is unreachable, don't block all
        # traffic. Log loudly so the disabled-limiter state is visible, not silent.
        logger.warning("rate_limit.config_unavailable_fail_open", exc_info=True)
        return False, 0

    await cache.set_cached(_CONFIG_CACHE_KEY, {"enabled": enabled, "limit": limit}, ttl=30)
    return bool(enabled), int(limit)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path in _EXEMPT_PATHS or not hasattr(request.app.state, "cache"):
            return await call_next(request)

        cache = request.app.state.cache
        session_factory = request.app.state.session_factory
        enabled, limit = await _rate_limit_config(cache, session_factory)
        if not enabled:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        window = int(time.time() // 60)
        count = await cache.incr(f"ratelimit:{client_ip}:{window}", ttl=90)

        if count > limit:
            logger.warning("rate_limit.exceeded", client_ip=client_ip, count=count, limit=limit)
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

        return await call_next(request)
