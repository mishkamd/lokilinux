"""
LokiLinux — Bearer token validation via Better Auth session endpoint.

Better Auth emite opaque session tokens (nu JWT RS256).
Validăm prin GET {better_auth_url}/api/auth/get-session cu header Authorization: Bearer <token>.
Cache per-token în Redis (TTL 60s) pentru a evita overhead per-request.
"""

import asyncio
from typing import Any, Optional

import httpx
from fastapi import Depends, Header, HTTPException

from lokilinux.cache import RedisCache
from lokilinux.config import get_settings
from lokilinux.dependencies import get_cache


async def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    cache: RedisCache = Depends(get_cache),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization[7:]
    cache_key = f"ba:session:{token}"
    down_key = f"ba:down:{token}"

    # Redis cache 60s — evită request la Better Auth per fiecare endpoint
    cached = await cache.get_cached(cache_key)
    if cached:
        return cached  # type: ignore[return-value]

    # Negative cache: dacă auth a fost down recent, degradează rapid fără să-l lovim iar (5s)
    if await cache.get_cached(down_key):
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    settings = get_settings()
    # Circuit breaker simplu: 2 încercări cu 1s delay pe erori tranzitorii (network/5xx)
    resp: Optional[httpx.Response] = None
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{settings.better_auth_url}/api/auth/get-session",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if resp.status_code < 500:
                break  # răspuns definitiv (200/401/403/4xx) — nu reîncerca
        except httpx.RequestError as exc:
            last_exc = exc
            resp = None
        if attempt == 0:
            await asyncio.sleep(1.0)

    if resp is None or resp.status_code >= 500:
        await cache.set_cached(down_key, True, ttl=5)
        detail = f"Auth service unreachable: {last_exc}" if resp is None else "Auth service error"
        raise HTTPException(status_code=503, detail=detail)

    if resp.status_code == 401 or resp.status_code == 403:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Auth service error")

    data = resp.json()
    if not data or not data.get("user"):
        raise HTTPException(status_code=401, detail="No active session")

    user = data["user"]
    # normalizează role la uppercase pentru require_role() care compară cu "ADMIN" etc.
    if "role" in user:
        user["role"] = (user["role"] or "user").upper()

    await cache.set_cached(cache_key, user, ttl=60)
    return user  # type: ignore[return-value]
