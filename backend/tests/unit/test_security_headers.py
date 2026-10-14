"""Security headers middleware (ROADMAP P1r-1.1), driven with a bare ASGI app."""

import asyncio

from lokilinux.middleware.security_headers import SecurityHeadersMiddleware


async def _app(scope, receive, send):
    headers = [(b"content-type", b"application/json")]
    if scope["path"] == "/custom":
        headers.append((b"x-frame-options", b"SAMEORIGIN"))
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": b"{}"})


def _headers(path):
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": path, "headers": []}
    asyncio.run(SecurityHeadersMiddleware(_app)(scope, receive, send))
    return dict(sent[0]["headers"])


def test_base_headers_added():
    h = _headers("/api/v1/servers")
    assert h[b"x-content-type-options"] == b"nosniff"
    assert h[b"x-frame-options"] == b"DENY"
    assert h[b"referrer-policy"] == b"strict-origin-when-cross-origin"
    assert b"strict-transport-security" in h


def test_api_gets_csp_docs_do_not():
    csp = _headers("/api/v1/servers")[b"content-security-policy"]
    assert csp == b"default-src 'none'; frame-ancestors 'none'"
    assert b"content-security-policy" not in _headers("/docs")
    assert b"content-security-policy" not in _headers("/openapi.json")


def test_route_set_header_is_not_overwritten():
    assert _headers("/custom")[b"x-frame-options"] == b"SAMEORIGIN"
