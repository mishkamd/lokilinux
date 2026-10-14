"""
Request body size cap (ROADMAP P1r-1.3).

Limits are per path prefix, first match wins; anything else gets DEFAULT_LIMIT.
A declared Content-Length over the limit is refused before the app runs. For
chunked bodies the bytes are counted as they are received, and the request is
refused once the count passes the limit.

Once the app has started a response, its status can't change, so a limit hit
at that point just aborts the request. Pure ASGI, like security_headers.py.
"""

from starlette.responses import JSONResponse

DEFAULT_LIMIT = 10 * 1024 * 1024
_SMALL = 64 * 1024
_OTLP = 16 * 1024 * 1024  # same ceiling as the gRPC message limit


def body_limit_rules(settings) -> tuple[tuple[str, int], ...]:  # type: ignore[no-untyped-def]
    return (
        ("/api/v1/agents/register", _SMALL),
        ("/api/v1/auth/", _SMALL),
        ("/api/v1/storage/", settings.s3_max_upload_bytes),
        ("/api/v1/otlp/", _OTLP),
    )


class _BodyTooLargeError(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app, *, rules: tuple[tuple[str, int], ...]):  # type: ignore[no-untyped-def]
        self.app = app
        self.rules = rules

    def _limit_for(self, path: str) -> int:
        for prefix, limit in self.rules:
            if path.startswith(prefix):
                return limit
        return DEFAULT_LIMIT

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope["path"])
        declared = next((v for k, v in scope["headers"] if k == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._reject(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive():  # type: ignore[no-untyped-def]
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLargeError()
            return message

        async def tracked_send(message):  # type: ignore[no-untyped-def]
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _BodyTooLargeError:
            if started:
                raise
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope, receive, send):  # type: ignore[no-untyped-def]
        response = JSONResponse({"detail": "Request body too large"}, status_code=413)
        await response(scope, receive, send)
