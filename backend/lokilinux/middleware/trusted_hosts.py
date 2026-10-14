"""
Host header allowlist (ROADMAP P1r-1.2).

Starlette's TrustedHostMiddleware can only block. This one has a log stage, so
the allowlist can be checked against the live stack before it rejects anything:

- log (default): unknown Host headers are logged and the request goes through.
- enforce: unknown Host headers get 400.
- off: middleware not registered.

Pure ASGI, like security_headers.py.
"""

from urllib.parse import urlsplit

import structlog
from starlette.responses import JSONResponse

logger = structlog.get_logger()

_BASE_HOSTS = frozenset({"localhost", "127.0.0.1", "lokilinux-api"})


def allowed_hosts(settings) -> frozenset[str]:  # type: ignore[no-untyped-def]
    names = set(_BASE_HOSTS)
    for url in (settings.platform_url, settings.frontend_url):
        host = urlsplit(url).hostname
        if host:
            names.add(host.lower())
    names.update(h.strip().lower() for h in settings.trusted_hosts.split(",") if h.strip())
    return frozenset(names)


def host_only(raw: str) -> str:
    host = raw.strip().lower()
    if host.startswith("["):  # [v6]:port
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:  # name:port
        return host.rsplit(":", 1)[0]
    return host


class TrustedHostsMiddleware:
    def __init__(self, app, *, allowed: frozenset[str], enforce: bool):  # type: ignore[no-untyped-def]
        self.app = app
        self.allowed = allowed
        self.enforce = enforce

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"host"), "")
        host = host_only(raw)
        if host in self.allowed:
            await self.app(scope, receive, send)
            return

        logger.warning("trusted_hosts.unknown_host", host=host, enforce=self.enforce)
        if self.enforce:
            await JSONResponse({"detail": "Invalid host header"}, status_code=400)(scope, receive, send)
            return
        await self.app(scope, receive, send)
