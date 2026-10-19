"""
Security response headers (ROADMAP P1r-1.1).

Pure ASGI, not BaseHTTPMiddleware: it only touches the response start message,
so streaming and file responses pass through untouched. Headers the route
already set are left alone.

The API serves JSON, so CSP is default-src 'none'. The OpenAPI docs load their
UI from a CDN, so /docs and /openapi.json are exempt from it.
"""

_BASE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
)
_API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
_CSP_EXEMPT_PREFIXES = ("/docs", "/openapi.json")


class SecurityHeadersMiddleware:
    def __init__(self, app):  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        csp_exempt = scope["path"].startswith(_CSP_EXEMPT_PREFIXES)

        async def send_with_headers(message):  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in _BASE_HEADERS:
                    if name not in present:
                        headers.append((name, value))
                if not csp_exempt and _API_CSP[0] not in present:
                    headers.append(_API_CSP)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
