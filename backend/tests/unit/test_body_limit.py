"""Request body cap (ROADMAP P1r-1.3), driven with a bare ASGI app."""

import asyncio

from lokilinux.middleware.body_limit import DEFAULT_LIMIT, BodyLimitMiddleware

RULES = (("/api/v1/agents/register", 64), ("/api/v1/storage/", 1000))


async def _app(scope, receive, send):
    total = 0
    while True:
        message = await receive()
        total += len(message.get("body", b""))
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(total).encode()})


def _status(path: str, chunks: list[bytes], *, content_length: int | None = None) -> int:
    sent = []
    queue = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]

    async def receive():
        return queue.pop(0) if queue else {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    headers = [(b"content-length", str(content_length).encode())] if content_length is not None else []
    scope = {"type": "http", "path": path, "headers": headers}
    asyncio.run(BodyLimitMiddleware(_app, rules=RULES)(scope, receive, send))
    return sent[0]["status"]


def test_declared_length_over_limit_is_refused_before_the_app():
    assert _status("/api/v1/agents/register", [b"x" * 100], content_length=100) == 413


def test_chunked_body_over_limit_is_refused():
    assert _status("/api/v1/agents/register", [b"x" * 40, b"x" * 40]) == 413


def test_body_at_limit_is_accepted():
    assert _status("/api/v1/agents/register", [b"x" * 64]) == 200


def test_storage_prefix_has_its_own_larger_limit():
    assert _status("/api/v1/storage/objects", [b"x" * 500]) == 200


def test_other_paths_use_the_default_limit():
    big = b"x" * (DEFAULT_LIMIT + 1)
    assert _status("/api/v1/servers", [big]) == 413
    assert _status("/api/v1/servers", [b"x" * 2048]) == 200
